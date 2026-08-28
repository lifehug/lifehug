"""O-E6 — one gap, one work id (T-Q-03, T-Q-04, T-Q-07).

The defect these tests exist for, probed against the code before the change:

```
substrate   work:c7f235f83e306d76b64fd4ce   missing_anchor / self / birth_date
keystone    work:5b18d0f7579cf7dfd0cab911   missing_anchor / birth / temporal_anchor
SAME?       False
```

Answer-once closure is BY IDENTITY. Two identities for one question means the
person answers their own birthday on Timeline and is asked for it by the daily
question the same week, and the whisper lane cannot suppress the item the day
is already asking.

Three properties, in the order they have to hold:

1. **Convergence** — both lanes derive the same id (T-Q-03).
2. **Continuity** — every id the gap has ever been addressed by resolves to
   the one it is addressed by now, through ONE lookup, at every door a stored
   reference arrives at (T-Q-04, T-Q-07).
3. **No third spelling** — the legacy vocabulary has exactly two homes in
   `system/`, both of them constant definitions, and nothing mints under it.

Synthetic data only; NEVER references any real vault.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import mirror_work as mw  # noqa: E402
import question_planner as qp  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline  # noqa: E402
import timeline_interaction as ti  # noqa: E402

SYSTEM = ROOT / "system"

#: The pre-O-E6 spelling of the birth-origin ask, minted the way the keystone
#: lane minted it. Written out rather than derived, because a test that derives
#: the thing it is proving migrated proves nothing.
LEGACY_BIRTH_ID = tp.derive_work_item_id(
    kind="missing_anchor",
    subject_ref="birth",
    event_ref=None,
    requested_field="temporal_anchor",
)

CANONICAL_BIRTH_ID = twi.birth_origin_work_item_id()


def a_birth_item() -> dict:
    """The fold's own row for the owner's missing birthday."""
    return tp.validate_temporal_work_item(
        {
            "kind": "missing_anchor",
            "state": "open",
            "subject_ref": "self",
            "requested_field": "birth_date",
            "prompt_intent": "What is your date of birth?",
            "allowed_surfaces": ["timeline", "whisper", "daily_question"],
            "created_at": "2026-08-27T00:00:00Z",
            # As the fold states it: the scaffold, under `temporal-score:2`.
            "system_value": twi.birth_origin_system_value(0),
            "score_rule": twi.BIRTH_ORIGIN_SCORE_RULE,
        }
    )


class Convergence(unittest.TestCase):
    """T-Q-03 — the keystone path and the substrate path mint ONE id."""

    def test_the_two_lanes_used_to_disagree(self):
        """The negative, kept executable so the fix cannot silently rot."""
        self.assertNotEqual(
            LEGACY_BIRTH_ID,
            CANONICAL_BIRTH_ID,
            "the legacy spelling no longer differs — this suite proves nothing",
        )

    def test_the_keystone_lane_now_lands_on_the_substrates_id(self):
        self.assertEqual(qp.timeline_work_item_id(anchor="birth"), CANONICAL_BIRTH_ID)

    def test_every_spelling_of_the_birth_anchor_lands_there_too(self):
        for anchor in twi.BIRTH_ANCHOR_KEYS:
            with self.subTest(anchor=anchor):
                self.assertEqual(
                    qp.timeline_work_item_id(anchor=anchor), CANONICAL_BIRTH_ID
                )

    def test_an_anchor_kind_settles_it_when_the_key_is_unfamiliar(self):
        """The anchor index's own `kind` is authoritative when a caller has it."""
        self.assertEqual(
            qp.timeline_work_item_id(anchor="landmark:when-i-was-born",
                                     anchor_kind="birth"),
            CANONICAL_BIRTH_ID,
        )

    def test_an_adapted_keystone_is_the_same_item_the_fold_mints(self):
        item = qp.work_item_from_keystone(
            {"anchor": "birth", "leverage": 4,
             "probe": {"text": "When were you born?"}},
            now="2026-08-27T00:00:00Z",
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["work_item_id"], a_birth_item()["work_item_id"])
        self.assertEqual(item["subject_ref"], "self")
        self.assertEqual(item["requested_field"], "birth_date")

    def test_somebody_elses_birthday_is_NOT_the_owners_birth_origin(self):
        """The rule has to be narrow or it folds four children into one gap."""
        moms = tp.derive_work_item_id(
            kind="missing_anchor", subject_ref="person:mom",
            event_ref=None, requested_field="birth_date",
        )
        self.assertNotEqual(moms, CANONICAL_BIRTH_ID)
        self.assertEqual(
            twi.canonical_work_item_id(
                kind="missing_anchor", subject_ref="person:mom",
                requested_field="birth_date",
            ),
            moms,
        )

    def test_an_ordinary_anchor_keeps_its_own_subject_and_widens_its_field(self):
        canonical = twi.canonical_ask(
            kind="missing_anchor", subject_ref="period:mesa",
            requested_field=twi.LEGACY_REQUESTED_FIELD,
        )
        self.assertEqual(canonical, ("missing_anchor", "period:mesa", None, "date"))

    def test_a_gap_about_nothing_still_gets_no_identity(self):
        self.assertEqual(qp.timeline_work_item_id(), "")
        self.assertEqual(twi.canonical_work_item_id(kind="missing_anchor"), "")


class TheAliasMap(unittest.TestCase):
    """T-Q-07 — derived, published in one generation, never a guess."""

    def test_the_legacy_id_maps_onto_the_canonical_one(self):
        aliases = twi.work_item_aliases([a_birth_item()])
        self.assertEqual(aliases.get(LEGACY_BIRTH_ID), CANONICAL_BIRTH_ID)

    def test_it_is_derived_so_rebuilding_it_is_byte_identical(self):
        item = a_birth_item()
        self.assertEqual(twi.work_item_aliases([item]), twi.work_item_aliases([item]))

    def test_a_canonical_id_is_never_its_own_alias(self):
        self.assertNotIn(CANONICAL_BIRTH_ID, twi.work_item_aliases([a_birth_item()]))

    def test_an_alias_never_crosses_kind(self):
        """A coarse birthday and a missing one are different questions.

        Folding them would let answering one close the other, which is the
        exact failure the identity keys exist to prevent.
        """
        precision = tp.derive_work_item_id(
            kind="precision_gap", subject_ref="self",
            event_ref=None, requested_field="birth_date",
        )
        aliases = twi.work_item_aliases([a_birth_item()])
        self.assertNotIn(precision, aliases)
        for legacy, canonical in aliases.items():
            with self.subTest(legacy=legacy):
                self.assertEqual(canonical, CANONICAL_BIRTH_ID)

    def test_two_items_claiming_one_legacy_id_drop_it_rather_than_guess(self):
        """A wrong pick silently reroutes one person's answer. Refuse instead.

        The contested id is the LEGACY-FIELD twin of `self` — every canonical
        item with that subject and no event derives it, so two such items make
        the map ambiguous by construction rather than by contrivance.
        """
        contested = tp.derive_work_item_id(
            kind="missing_anchor", subject_ref="self",
            event_ref=None, requested_field=twi.LEGACY_REQUESTED_FIELD,
        )
        first = a_birth_item()
        self.assertIn(contested, twi.work_item_aliases([first]))

        # A second canonical item, same kind and subject, different field:
        # `start_date` is a real substrate spelling and derives the same twin.
        rival = dict(first)
        rival["requested_field"] = "start_date"
        rival["work_item_id"] = tp.derive_work_item_id(
            kind="missing_anchor", subject_ref="self",
            event_ref=None, requested_field="start_date",
        )
        self.assertNotEqual(rival["work_item_id"], first["work_item_id"])
        self.assertIn(contested, twi.legacy_work_item_ids(rival))

        both = twi.work_item_aliases([first, rival])
        self.assertNotIn(contested, both,
                         "a contested alias was resolved by guessing")
        # And the uncontested ones survive: one ambiguity is not a reason to
        # throw away every other id the gap has been addressed by.
        self.assertEqual(both.get(LEGACY_BIRTH_ID), CANONICAL_BIRTH_ID)

    def test_resolution_never_invents_an_identity(self):
        self.assertEqual(twi.resolve_work_item_id("work:unknown"), "work:unknown")
        self.assertEqual(twi.resolve_work_item_id(""), "")
        self.assertEqual(twi.resolve_work_item_id(None), "")

    def test_a_cyclic_map_terminates_rather_than_hanging(self):
        cycle = {"work:a": "work:b", "work:b": "work:a"}
        self.assertIn(twi.resolve_work_item_id("work:a", aliases=cycle),
                      ("work:a", "work:b"))

    def test_a_chain_resolves_to_its_end(self):
        chain = {"work:a": "work:b", "work:b": "work:c"}
        self.assertEqual(twi.resolve_work_item_id("work:a", aliases=chain), "work:c")

    def test_the_fold_publishes_the_map_beside_the_items(self):
        import temporal_store as ts  # noqa: PLC0415
        import temporal_timeline as tt  # noqa: PLC0415

        result = tt.derive_calculated_timeline(
            {"version": ts.INDEX_VERSION, "claims": []},
            owner_ref="self",
            now="2026-08-27T00:00:00Z",
        )
        self.assertEqual(
            [row["work_item_id"] for row in result.work_items], [CANONICAL_BIRTH_ID]
        )
        self.assertEqual(result.work_item_aliases.get(LEGACY_BIRTH_ID),
                         CANONICAL_BIRTH_ID)
        self.assertEqual(result.to_dict()["work_item_aliases"],
                         result.work_item_aliases)


class EveryDoorResolves(unittest.TestCase):
    """T-Q-04 / T-Q-07 — a stored reference keeps opening, at every door.

    Each case drives a REAL entry point with the LEGACY id and asserts it lands
    on the canonical item. A door added later without resolution fails
    :class:`NoThirdSpelling` below, not this class — which is why both exist.
    """

    ALIASES = {LEGACY_BIRTH_ID: CANONICAL_BIRTH_ID}

    def test_the_bank_ledger_ticks_the_canonical_item(self):
        """T-Q-04: answered on any surface, closed on all of them."""
        bank = (
            "# Questions\n\n## A: Origins\n\n"
            "- [x] A7: When were you born?\n"
            f"  <!-- timeline_probe: tl:birth; anchor: birth; leverage: 4; "
            f"work_item: {LEGACY_BIRTH_ID} -->\n"
        )
        rows = qp.bank_work_items(bank, aliases=self.ALIASES)
        self.assertIn(CANONICAL_BIRTH_ID, rows)
        self.assertNotIn(LEGACY_BIRTH_ID, rows)
        self.assertEqual(
            qp.work_item_states_from_bank(bank, aliases=self.ALIASES),
            {CANONICAL_BIRTH_ID: "answered"},
        )
        closed = qp.close_answered_work_items(
            [a_birth_item()], question_bank_text=bank, aliases=self.ALIASES
        )
        self.assertEqual(closed[0]["state"], "answered")

    def test_an_item_answered_under_the_old_id_is_not_minted_again(self):
        """T-Q-07's own sentence: two ids cannot mint two questions."""
        bank = (
            "# Questions\n\n## A: Origins\n\n"
            "- [ ] A7: When were you born?\n"
            f"  <!-- timeline_probe: tl:birth; anchor: birth; leverage: 4; "
            f"work_item: {LEGACY_BIRTH_ID} -->\n"
        )
        candidates = qp.queue_candidates(
            [a_birth_item()], question_bank_text=bank, aliases=self.ALIASES
        )
        self.assertEqual(candidates, [])
        # Without the map it would be a fresh candidate — which is the bug.
        self.assertTrue(
            qp.queue_candidates([a_birth_item()], question_bank_text=bank, aliases={})
        )

    def test_a_pre_marker_bank_row_derives_the_canonical_id_from_its_anchor(self):
        bank = (
            "# Questions\n\n## A: Origins\n\n"
            "- [ ] A7: When were you born?\n"
            "  <!-- timeline_probe: tl:birth; anchor: birth; leverage: 4 -->\n"
        )
        self.assertIn(CANONICAL_BIRTH_ID, qp.bank_work_items(bank))

    def test_the_queue_dedupes_a_legacy_row_against_a_canonical_one(self):
        legacy = dict(a_birth_item())
        legacy["work_item_id"] = LEGACY_BIRTH_ID
        deduped = qp._dedupe_work_items([legacy, a_birth_item()], aliases=self.ALIASES)
        self.assertEqual(len(deduped), 1)

    def test_a_session_target_minted_under_the_old_id_still_opens(self):
        target = ti.work_item_target(
            {
                "kind": "work_item",
                "item_kind": "missing_anchor",
                "ref": LEGACY_BIRTH_ID,
                "label": "When were you born?",
            },
            aliases=self.ALIASES,
        )
        self.assertIsNotNone(target, "a stored Play target stopped opening")
        self.assertEqual(target["work_item_id"], CANONICAL_BIRTH_ID)

    def test_a_target_carrying_its_own_map_resolves_without_a_caller_knowing(self):
        target = ti.work_item_target(
            {
                "kind": "work_item",
                "item_kind": "missing_anchor",
                "ref": LEGACY_BIRTH_ID,
                "work_item_aliases": self.ALIASES,
            }
        )
        self.assertEqual(target["work_item_id"], CANONICAL_BIRTH_ID)

    def test_an_unknown_target_id_is_left_exactly_as_it_arrived(self):
        target = ti.work_item_target(
            {"kind": "work_item", "item_kind": "missing_anchor", "ref": "work:zzz"},
            aliases=self.ALIASES,
        )
        self.assertEqual(target["work_item_id"], "work:zzz")

    def test_mirror_reads_a_stale_generations_id_as_the_current_one(self):
        legacy = {
            "kind": "identity_uncertain",
            "state": "open",
            "subject_ref": "unresolved:aj",
            "requested_field": "identity",
            "prompt_intent": "Who is AJ?",
            "allowed_surfaces": ["mirror"],
            "created_at": "2026-08-27T00:00:00Z",
        }
        row = mw.row_for(legacy, {"claims": []})
        self.assertIsNotNone(row)
        aliases = {row.work_item_id: "work:" + ("b" * 24)}
        moved = mw.row_for(legacy, {"claims": []}, aliases=aliases)
        self.assertEqual(moved.work_item_id, "work:" + ("b" * 24))
        self.assertEqual(moved.play["ref"], "work:" + ("b" * 24))

    def test_mirrors_lookup_is_the_shared_one(self):
        self.assertEqual(
            mw.resolve_work_item_id(LEGACY_BIRTH_ID, aliases=self.ALIASES),
            CANONICAL_BIRTH_ID,
        )


class NoThirdSpelling(unittest.TestCase):
    """The guard: nothing compares work ids without going through the lookup."""

    #: The legacy vocabulary's only two homes, each a constant DEFINITION.
    #: `question_planner` keeps its name for readers that already import it and
    #: is asserted equal to the definition below.
    LEGACY_LITERAL_HOMES = {
        "temporal_work_items.py": "LEGACY_REQUESTED_FIELD",
        "question_planner.py": "TIMELINE_REQUESTED_FIELD",
    }

    def test_the_deprecated_name_still_means_the_same_string(self):
        self.assertEqual(qp.TIMELINE_REQUESTED_FIELD, twi.LEGACY_REQUESTED_FIELD)

    def test_the_legacy_spelling_has_exactly_two_homes_and_both_are_constants(self):
        found: dict[str, list[str]] = {}
        for path in sorted(SYSTEM.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Constant)
                        and node.value == twi.LEGACY_REQUESTED_FIELD):
                    continue
                found.setdefault(path.name, []).append("constant")
        self.assertEqual(
            sorted(found), sorted(self.LEGACY_LITERAL_HOMES),
            "a third spelling of the legacy requested field appeared — the two "
            "identities this release collapsed are growing back",
        )
        for name, expected in self.LEGACY_LITERAL_HOMES.items():
            module = ast.parse((SYSTEM / name).read_text(encoding="utf-8"))
            assigned = {
                target.id
                for statement in module.body
                if isinstance(statement, ast.Assign)
                for target in statement.targets
                if isinstance(target, ast.Name)
                and isinstance(statement.value, ast.Constant)
                and statement.value.value == twi.LEGACY_REQUESTED_FIELD
            }
            with self.subTest(module=name):
                self.assertIn(expected, assigned)

    def test_nothing_outside_the_vocabulary_mints_a_raw_work_item_id(self):
        """`derive_work_item_id` is the digest; canonicalization is the door.

        Every caller in `system/` reaches it through `temporal_work_items`
        (which owns the canonical tuple) or through
        `temporal_projection.validate_temporal_work_item` (which derives from
        an item whose tuple the fold already canonicalized). A NEW direct
        caller is how a third identity gets minted, so it has to be declared.
        """
        allowed = {"temporal_projection.py", "temporal_work_items.py"}
        callers = set()
        for path in sorted(SYSTEM.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else ""
                )
                if name == "derive_work_item_id":
                    callers.add(path.name)
        self.assertEqual(callers, allowed, f"undeclared minter(s): {callers - allowed}")

    def test_every_declared_door_resolves_its_reference(self):
        """The behavioural half: each door, driven with the legacy id.

        A source scan cannot prove a door RESOLVES, only that it exists, so the
        table is exercised rather than read. Adding a door means adding a row.
        """
        aliases = {LEGACY_BIRTH_ID: CANONICAL_BIRTH_ID}
        doors = {
            "question_planner.resolve_work_item_id":
                lambda: qp.resolve_work_item_id(LEGACY_BIRTH_ID, aliases=aliases),
            "mirror_work.resolve_work_item_id":
                lambda: mw.resolve_work_item_id(LEGACY_BIRTH_ID, aliases=aliases),
            "temporal_work_items.resolve_work_item_id":
                lambda: twi.resolve_work_item_id(LEGACY_BIRTH_ID, aliases=aliases),
            "timeline_interaction.work_item_target": lambda: ti.work_item_target(
                {"kind": "work_item", "item_kind": "missing_anchor",
                 "ref": LEGACY_BIRTH_ID},
                aliases=aliases,
            )["work_item_id"],
            "question_planner.bank_work_items": lambda: next(iter(qp.bank_work_items(
                "# Questions\n\n## A: Origins\n\n"
                "- [ ] A7: When were you born?\n"
                f"  <!-- timeline_probe: tl:birth; anchor: birth; leverage: 4; "
                f"work_item: {LEGACY_BIRTH_ID} -->\n",
                aliases=aliases,
            ))),
        }
        for name, door in doors.items():
            with self.subTest(door=name):
                self.assertEqual(door(), CANONICAL_BIRTH_ID)


class TheKeystoneRowCarriesIt(unittest.TestCase):
    """T-Q-04's other half — the identity a host's "today" payload needs."""

    def test_a_keystone_row_carries_its_canonical_work_item_id(self):
        data = {
            "anchors": {"birth": {"label": "when you were born", "kind": "birth"}},
            "periods": [],
            "unplaced_events": [],
            "event_lineup": {},
            "entity_lineup": {},
        }
        rows = timeline.keystones(data)
        for row in rows:
            with self.subTest(anchor=row.get("anchor")):
                self.assertIn("work_item_id", row)

    def test_the_row_and_the_planner_agree_on_the_identity(self):
        row = {"anchor": "birth", "leverage": 3,
               "probe": {"text": "When were you born?"}}
        self.assertEqual(
            qp.work_item_from_keystone(row, now="2026-08-27T00:00:00Z")["work_item_id"],
            qp.timeline_work_item_id(anchor="birth"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
