"""E-L2b — the containment NEGATIVE: drag-out, rebuild, undo (audit H5).

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §0.1
H5, §4.1 condition 6, §5 rules 1–2, §12 rows 12, 29 and 30, §14.2.

    Verified: retraction of a membership is durable, `not_same` is durable and
    consulted by the binder … Two things the audit did not see: `not_same` is
    the wrong relation for "not in this container" (it asserts non-identity,
    and the containment rung never checks it), and the binding relation `none`
    already exists.

So a removal is a `stated` `none` binding superseding the active `part_of`,
plus an `adopt` envelope when the episode had not been touched by a person
before — and the rung gains one condition, `no_human_decision_on_pair`, so no
rebuild, sweep or rule bump re-files that pair.

Row 12 is asserted from the PUBLISHED PROJECTION FILE, not from an in-memory
recomputation, across all four states: auto-placed → dragged out → `state/`
deleted and rebuilt (it must stay out) → undone.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import episode_fold as ef  # noqa: E402
import event_identity as ei  # noqa: E402
import identity_questions as iq  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"

ROSTERS = {
    "place": {"type": "place", "entities": [
        {"name": "Cedarport", "slug": "cedarport",
         "aliases": ["the Cedarport house"]},
    ]},
}

STORY_SOURCE = "classification:answers-a1#aaa1"


def value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def story_claim() -> dict:
    return tc.validate_temporal_claim({
        "source_kind": "conversation",
        "source_ref": {"source_id": STORY_SOURCE, "revision": "sha256:" + "a" * 64},
        "evidence": [{"quote": "A storm dropped a tree on the Cedarport house."}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": "occurrence",
        "subject_mention": "I",
        "event_mention": "The tree fell on the Cedarport house",
        "event_kind": "moment",
        "event_ref": tp.derive_node_id(
            node_kind="event", event_kind="moment",
            subject_refs=["I"], discriminator=STORY_SOURCE,
        ),
    })


class DragOutCase(unittest.TestCase):
    """One stay, one undated story inside it, and the four states of row 12."""

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2b-neg-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        rosters = self.root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        for kind, snapshot in ROSTERS.items():
            (rosters / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")
        lp.file_landmark_record(
            self.root, "residences",
            {"label": "Cedarport", "city": "Cedarport",
             "span": {"start": value("1996-06"), "end": value("2001-08")}},
            ordinal=1, now=NOW,
        )
        row = story_claim()
        ts.write_receipt(self.root, {
            "source_ref": row["source_ref"],
            "extractor_version": "classifier:1",
            "created_at": "2026-08-30T00:00:00Z",
            "claims": [row],
        })
        ts.rebuild_active_index(self.root)
        self.bind()
        self.publish()

    # -- the acts --------------------------------------------------------

    def bind(self):
        self.binder = eb.bind_episodes(
            self.root, apply=True, now=NOW, containment_authority="applied",
        )
        return self.binder

    def publish(self) -> dict:
        pub.publish(self.root, roster_snapshot=(), now=NOW)
        return pub.read_projection(self.root) or {}

    def published_containments(self) -> list:
        payload = pub.read_projection(self.root) or {}
        rows = []
        for node in payload.get("nodes") or ():
            for row in node.get("containments") or ():
                rows.append((node["node_id"], row["episode_id"], row["relation"],
                             row["origin"]))
        return sorted(rows)

    def published_window(self) -> object:
        payload = pub.read_projection(self.root) or {}
        for node in payload.get("nodes") or ():
            if node.get("label") == "The tree fell on the Cedarport house":
                return node.get("possible_temporal_value")
        return None

    def pair(self) -> tuple[str, str]:
        rows = self.published_containments()
        self.assertTrue(rows, "nothing was contained; the fixture is wrong")
        telling = ei.landmark_telling_ref  # noqa: F841 - documented below
        # The (telling, episode) pair the rung filed, read back from the
        # binding records rather than recomputed from the container's id.
        for record in ei.load_event_identities(self.root):
            if record.get("relation") == "part_of" and record.get("status") == "active":
                return record["telling_ref"], record["episode_id"]
        raise AssertionError("no part_of binding was filed")

    def delete_derived_state(self) -> None:
        """CERT-11's own gesture: every DERIVED identity byte, and the manifest.

        `state/temporal_claims/receipts` is deliberately NOT touched — a
        receipt is authored substrate that happens to live under `state/`, and
        deleting it would delete the claims themselves rather than the
        inferences drawn from them (§3.5's authored/inferred split).
        """
        shutil.rmtree(self.root / ei.IDENTITY_STATE_DIR, ignore_errors=True)
        manifest = self.root / ei.TELLING_MANIFEST_FILE
        if manifest.exists():
            manifest.unlink()
        index = ts.active_index_path(self.root)
        if index.exists():
            index.unlink()
        ts.rebuild_active_index(self.root)

    def container_telling(self) -> str:
        for container in self.binder["plan"].containers.values():
            return container.opened_by
        raise AssertionError("no container")


class RowTwelveTheFourStates(DragOutCase):
    """§12 row 12, from the published file at every step."""

    def test_the_four_states_from_the_published_projection(self):
        telling, episode = self.pair()

        # (1) auto-placed: the window is drawn and the record is the rung's.
        self.assertEqual(
            self.published_containments(),
            [(row[0], episode, "part_of", "deterministic")
             for row in self.published_containments()],
        )
        self.assertIsNotNone(self.published_window())

        # (2) dragged out: a stated `none` supersedes the `part_of`.
        removal = iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=self.container_telling(),
            reason="that happened at my parents' place, not here", now=NOW,
        )
        self.assertTrue(removal["created"])
        self.assertEqual(removal["relation"], ei.SPLIT_DEPARTURE_RELATION)
        self.publish()
        self.assertEqual(self.published_containments(), [])
        self.assertIsNone(self.published_window())

        # (3) a FULL REBUILD files nothing on the pair. Deleting `state/` takes
        # the deterministic binding with it; the person's `none` lives under
        # `sources/` and survives, and condition 6 reads it.
        self.delete_derived_state()
        plan = self.bind()["plan"]
        self.assertEqual(
            [row["condition"] for row in plan.containment_negatives],
            [ec.NO_HUMAN_DECISION_CONDITION],
        )
        self.assertEqual(plan.counts["containment_members"], 0)
        self.publish()
        self.assertEqual(self.published_containments(), [])
        self.assertIsNone(self.published_window())

        # (4) undone: a stated `part_of` supersedes the `none`, and from then
        # on the pair is human-placed rather than back in the rung's hands.
        undo = iq.restore_to_container(
            self.root, telling_ref=telling, episode_id=episode, now=NOW,
        )
        self.assertTrue(undo["created"])
        self.publish()
        rows = self.published_containments()
        self.assertEqual([(row[2], row[3]) for row in rows], [("part_of", "stated")])
        self.assertIsNotNone(self.published_window())

    def test_the_precision_question_survives_every_state(self):
        """§7.1 / H6: the window is an improvement on the question, never its
        removal, and taking the window away does not remove it either."""
        telling, episode = self.pair()
        for _step in range(2):
            payload = pub.read_projection(self.root) or {}
            kinds = {item["kind"] for item in payload.get("work_items") or ()}
            self.assertIn("precision_gap", kinds)
            iq.remove_from_container(
                self.root, telling_ref=telling, episode_id=episode, now=NOW)
            self.publish()


class TheRemovalItself(DragOutCase):
    """§5 rule 1's mechanism, record by record."""

    def test_it_is_a_none_binding_at_stated_origin_under_sources(self):
        telling, episode = self.pair()
        iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=self.container_telling(), now=NOW)
        filed = [row for row in ei.load_event_identities(self.root)
                 if row["relation"] == ei.SPLIT_DEPARTURE_RELATION]
        self.assertEqual(len(filed), 1)
        self.assertEqual(filed[0]["origin"], "stated")
        self.assertTrue(filed[0]["supersedes"])
        self.assertTrue(
            (self.root / ei.HUMAN_BINDINGS_DIR).exists(),
            "a person's decision lives under sources/, never under state/",
        )

    def test_it_supersedes_the_rungs_own_record(self):
        telling, episode = self.pair()
        before = [row for row in ei.load_event_identities(self.root)
                  if row["relation"] == "part_of"][0]
        iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode, now=NOW)
        after = [row for row in ei.load_event_identities(self.root)
                 if row["relation"] == ei.SPLIT_DEPARTURE_RELATION][0]
        self.assertEqual(after["supersedes"], before["identity_id"])

    def test_it_adopts_an_episode_no_person_had_touched(self):
        """Event identity's lifecycle row 3: the moment a person acts on a
        deterministic episode, its identity becomes durable human authority."""
        telling, episode = self.pair()
        self.assertFalse(ei.is_adopted(self.root, episode))
        result = iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=self.container_telling(), now=NOW)
        self.assertTrue(result["adopted"])
        self.assertTrue(ei.is_adopted(self.root, episode))

    def test_the_adopt_envelope_says_how_the_container_id_was_minted(self):
        """A recorder-minted container has no create envelope at all, so the
        inputs are re-derived from the telling that opened it rather than left
        blank — the difference between "durable" and "durable and explainable"."""
        telling, episode = self.pair()
        opened_by = self.container_telling()
        iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=opened_by, now=NOW)
        adopts = [row for row in ei.load_episode_operations(self.root)
                  if row["op"] == "adopt"]
        self.assertEqual(len(adopts), 1)
        inputs = adopts[0]["adopted_canonical_inputs"]
        self.assertEqual(inputs["member_refs_sorted"], [opened_by])
        self.assertEqual(inputs["authority"], "deterministic")
        self.assertEqual(inputs["op"], "create")
        # The carried inputs re-derive the id they were carried for.
        self.assertEqual(ec.container_episode_id(opened_by), episode)

    def test_removing_twice_writes_nothing_the_second_time(self):
        telling, episode = self.pair()
        first = iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode, now=NOW)
        second = iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode, now=NOW)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        filed = [row for row in ei.load_event_identities(self.root)
                 if row["relation"] == ei.SPLIT_DEPARTURE_RELATION]
        self.assertEqual(len(filed), 1)

    def test_undoing_twice_writes_nothing_the_second_time(self):
        telling, episode = self.pair()
        iq.remove_from_container(self.root, telling_ref=telling,
                                 episode_id=episode, now=NOW)
        first = iq.restore_to_container(self.root, telling_ref=telling,
                                        episode_id=episode, now=NOW)
        second = iq.restore_to_container(self.root, telling_ref=telling,
                                         episode_id=episode, now=NOW)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])

    def test_an_undo_of_a_pair_nobody_removed_is_a_named_refusal(self):
        """A pair carrying an active `part_of` is an idempotent no-op (the
        undo is already true); a pair carrying nothing at all has no removal
        to undo, and saying so is better than filing a placement nobody asked
        for."""
        _telling, episode = self.pair()
        stranger = "classification:answers-z9#zzz9"
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.restore_to_container(self.root, telling_ref=stranger,
                                    episode_id=episode, now=NOW)
        self.assertEqual(caught.exception.code, "containment_restore_needs_removal")

    def test_undoing_a_pair_that_is_already_in_is_a_no_op(self):
        telling, episode = self.pair()
        result = iq.restore_to_container(self.root, telling_ref=telling,
                                         episode_id=episode, now=NOW)
        self.assertFalse(result["created"])
        self.assertEqual(result["relation"], "part_of")

    def test_a_confirmed_same_is_not_removed_by_this_verb(self):
        """A pair the person confirmed `same` is not up for revision here —
        that would contradict what they said rather than correct it. The way
        out of a wrong `same` is a split."""
        telling, episode = self.pair()
        standing = [row for row in ei.load_event_identities(self.root)
                    if row["relation"] == "part_of"][0]
        ei.file_event_identity(
            self.root, telling_ref=telling, episode_id=episode, relation="same",
            origin="confirmed", supersedes=standing["identity_id"], created_at=NOW,
        )
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.remove_from_container(self.root, telling_ref=telling,
                                     episode_id=episode, now=NOW)
        self.assertEqual(caught.exception.code, "containment_removal_needs_part_of")


class TheRungsOwnCondition(unittest.TestCase):
    """§4.1 condition 6 at the rung, proved to be what refuses.

    Driven directly rather than through `plan()`, because the binder ALSO
    drops such a pair through I3c's "already carries a binding" filter — a
    filter written for a different purpose that happens to coincide today.
    Coincidence is not a contract: this drives `containment_rows` with and
    without the condition and shows the row appearing and disappearing.
    """

    class _View:
        eligible = True
        dated = False
        bounds = None
        span = None
        span_open_ended = False
        event_kind = "moment"
        subject_entities: frozenset = frozenset()

        def __init__(self, telling_ref, entities):
            self.telling_ref = telling_ref
            self.label = "The tree fell on the Cedarport house"
            self.entities = frozenset(entities)

    def setUp(self) -> None:
        self.member = "classification:a1#aaa1"
        self.episode = ei.episode_id_for(ei.operation_digest(
            authority="deterministic", op="create", member_refs=["landmark:entry-1"]))
        self.container = ec.Container(
            key="unit:1", episode_id=self.episode, label="Cedarport",
            entities=frozenset({"place/cedarport"}), span=None,
            opened_by="landmark:entry-1", event_kind="residence",
        )
        # A container with a span, spelled the way `containers()` would.
        self.container = ec.Container(
            key="unit:1", episode_id=self.episode, label="Cedarport",
            entities=frozenset({"place/cedarport"}),
            span={"best": "1996-06/2001-08", "earliest": "1996-06",
                  "latest": "2001-08", "granularity": "range",
                  "basis": "stated", "confidence": "certain"},
            opened_by="landmark:entry-1", event_kind="residence",
        )
        self.views = {self.member: self._View(self.member, {"place/cedarport"})}
        self.found = {"unit:1": self.container}

    def test_without_the_condition_the_rung_files_the_pair(self):
        rows = ec.containment_rows(self.views, self.found)
        self.assertEqual([row["episode_id"] for row in rows], [self.episode])

    def test_with_a_human_decision_on_the_pair_it_refuses_and_says_so(self):
        negatives: list = []
        rows = ec.containment_rows(
            self.views, self.found,
            decided_pairs={(self.member, self.episode)},
            negatives=negatives,
        )
        self.assertEqual(rows, [])
        self.assertEqual([row["condition"] for row in negatives],
                         [ec.NO_HUMAN_DECISION_CONDITION])

    def test_human_decided_pairs_reads_both_clauses(self):
        part_of = ei.validate_event_identity({
            "telling_ref": self.member, "episode_id": self.episode,
            "relation": "part_of", "origin": "deterministic",
            "rule_id": ec.RULE_ID_ENTITY_SPAN,
        })
        removal = ei.validate_event_identity({
            "telling_ref": self.member, "episode_id": self.episode,
            "relation": ei.SPLIT_DEPARTURE_RELATION, "origin": "stated",
            "supersedes": part_of["identity_id"],
        })
        undo = ei.validate_event_identity({
            "telling_ref": self.member, "episode_id": self.episode,
            "relation": "part_of", "origin": "stated",
            "supersedes": removal["identity_id"],
        })
        pair = (self.member, self.episode)
        self.assertEqual(ec.human_decided_pairs([part_of]), frozenset())
        # Clause 1: an active stated binding of any relation.
        self.assertIn(pair, ec.human_decided_pairs([part_of, removal]))
        # Clause 2: the `none` still counts after an undo supersedes it — the
        # pair is the person's from that moment on, either way.
        self.assertIn(pair, ec.human_decided_pairs([part_of, removal, undo]))


class TheVerbIsBound(unittest.TestCase):
    """ADR 0021: a definition with no host binding is silent under-delivery."""

    def test_the_cli_verb_exists_and_takes_the_writer_lock(self):
        import lifehug  # noqa: PLC0415

        self.assertIn("containment-remove", lifehug.DIRECT_MUTATION_COMMANDS)
        parser = lifehug.build_parser() if hasattr(lifehug, "build_parser") else None
        if parser is not None:
            self.assertIn("containment-remove", parser._subparsers._group_actions[0].choices)


class RowTwentyNineARuleVersionBump(DragOutCase):
    """§12 row 29 — adopted pairs untouched by a new rule version.

    The removal ADOPTS the episode (row 3 of event identity's matrix), so the
    rule-version rule and condition 6 both hold over the same pair: `is_adopted`
    says the episode is a person's, and the rung refuses the pair by name.
    """

    def test_an_adopted_pair_is_untouched_and_the_refusal_is_reported(self):
        telling, episode = self.pair()
        iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=self.container_telling(), now=NOW)
        self.assertTrue(ei.is_adopted(self.root, episode))
        plan = self.bind()["plan"]
        self.assertEqual(plan.counts["containment_members"], 0)
        self.assertEqual(
            [(row["telling_ref"], row["episode_id"]) for row in plan.containment_negatives],
            [(telling, episode)],
        )


class RowThirtyTheNegativeSurvivesStateDeletion(DragOutCase):
    """§12 row 30, for the negatives: delete `state/` and the manifest, rebuild,
    byte-identical."""

    def test_the_projection_is_byte_identical_across_a_state_deletion(self):
        telling, episode = self.pair()
        iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=self.container_telling(), now=NOW)
        self.bind()
        before = pub.rebuild_signature(self.publish())
        self.delete_derived_state()
        self.bind()
        after = pub.rebuild_signature(self.publish())
        for key in ("nodes", "work_items"):
            self.assertEqual(
                json.dumps(after[key], sort_keys=True, default=str),
                json.dumps(before[key], sort_keys=True, default=str),
                key,
            )

    def test_the_deletion_removes_only_the_superseded_state_side_record(self):
        """The one number that legitimately MOVES, named rather than hidden.

        The rung's own `part_of` lives under `state/` and was superseded by
        the person's `none` the moment they dragged; deleting `state/` removes
        the superseded record itself. It contributed nothing to the drawing
        before the deletion and contributes nothing after — which is exactly
        what the two signatures above assert — so what changes is the raw
        record COUNT and not one byte of what the person sees.
        """
        telling, episode = self.pair()
        iq.remove_from_container(
            self.root, telling_ref=telling, episode_id=episode,
            container_telling_ref=self.container_telling(), now=NOW)
        def bindings_count() -> int:
            payload = pub.rebuild_signature(self.publish())
            return int((payload.get("identity_diagnostics") or {}).get(
                "active_bindings", len(ei.load_event_identities(self.root))))

        before = bindings_count()
        self.delete_derived_state()
        self.bind()
        after = bindings_count()
        self.assertEqual((before, after), (2, 1))
        surviving = ei.load_event_identities(self.root)
        self.assertEqual([row["relation"] for row in surviving],
                         [ei.SPLIT_DEPARTURE_RELATION])


if __name__ == "__main__":
    unittest.main()
