"""Event identity I1 — the fold applies bindings.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 —
§3.5 (what the fold consumes and publishes), §5.1–§5.4 (grouping, date,
containment, refusals), §5.6 (the two determinism properties) and §5.8's
lifecycle matrix rows **1, 3 and 10** proved at the FOLD level, where I0
proved them at the record level. The pure decisions applied here were settled
in `system/episode_fold_contract.py` (C3) and `system/event_identity.py`
(C1/C2) and are CALLED, never re-implemented — a second copy of the key the
substrate is identified by is the defect class this program exists to remove.

**The fixture is the founder's own shape** (`tests/goldens/
event_identity_i1_fold.json`), and it is the reason the program exists:
executed on his vault at `5690d37e`, Etherfuse is SIX nodes — a dated
work-history landmark, a dated conversation about the idea, and four UNDATED
classifier occurrences of the same company — so "needs placing" is inflated
with facts he already dated and Play can ask *"when did you start
Etherfuse?"* after he said May 2022. Here five tellings become one node with
one reconciled date and the four WHEN questions stop being asked. Every
name, date and word in the fixture is synthetic; NOTHING here reads
~/Workspace/dave.

Every negative test below was run against a build with its guard removed and
SEEN failing first; the evidence table is in the PR body.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "goldens" / "event_identity_i1_fold.json").read_text("utf-8")
)

NOW = "2026-08-30T12:00:00Z"
OWNER = "self"


# --------------------------------------------------------------------------
# Claims, shaped the way the two extractors actually file them
# --------------------------------------------------------------------------


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _claim(**overrides) -> dict:
    source = overrides.pop("source")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence somebody said")}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def birth_claim() -> dict:
    day = FIXTURE["owner_birth"]
    return _claim(
        claim_type="date", subject_mention="I", event_kind="birth",
        source="landmark:entry-birth", quote="I was born on 11 July 1981.",
        temporal_value={"best": day, "earliest": day, "latest": day,
                        "granularity": "day", "basis": "stated",
                        "confidence": "certain"},
    )


def telling_claim(row: dict) -> dict:
    """One telling's single claim, keyed so its telling ref IS its source id.

    That is not a convenience: C1's `telling_ref_for_claim` reads the receipt's
    declaration first and the claim's own ``source_ref.source_id`` second, and
    for both live extractors the source id already IS the telling — the
    classifier's per-event source id and the recorder's promoted entry id. A
    fixture that invented a third mint would be testing a shape nothing files.
    """
    dated = row.get("dated")
    common = {
        "subject_mention": row["subject"],
        "event_kind": row["event_kind"],
        "source": row["telling_ref"],
        "quote": row["quote"],
        "event_mention": row["quote"].rstrip("."),
    }
    if row["kind"] == "classifier":
        # Exactly what `classifier_claims` files: a per-moment `event_ref`,
        # without which every moment of the owner's would group into ONE node
        # and the fixture would be testing the wrong thing.
        common["event_ref"] = tp.derive_node_id(
            node_kind="event", event_kind=row["event_kind"],
            subject_refs=[row["subject"]], discriminator=row["telling_ref"],
        )
    if dated is None:
        return _claim(claim_type="occurrence", **common)
    return _claim(
        claim_type="date",
        temporal_value={"best": dated, "earliest": dated, "latest": dated,
                        "granularity": "month" if len(dated) == 7 else "year",
                        "basis": "stated", "confidence": "certain"},
        **common,
    )


def tellings(*roles: str) -> list:
    rows = FIXTURE["tellings"]
    if not roles:
        return list(rows)
    return [row for row in rows if row["role"] in roles]


def all_claims() -> list:
    return [birth_claim()] + [telling_claim(row) for row in tellings()]


def refs_of(*roles: str) -> list:
    return [row["telling_ref"] for row in tellings(*roles)]


# --------------------------------------------------------------------------
# The records, built the way I2's binder will build them
# --------------------------------------------------------------------------


def create_plan(members: tuple, *, kind: str, authority: str = "deterministic",
                origin: str = "deterministic") -> dict:
    operation_id = ei.operation_digest(
        authority=authority, op="create", rule_version=ei.IDENTITY_RULE_VERSION,
        member_refs=members,
    )
    episode_id = ei.episode_id_for(operation_id)
    bindings = [
        {"telling_ref": ref, "episode_id": episode_id, "relation": "same",
         "origin": origin, "rule_id": "R1", "operation_id": operation_id,
         "created_at": NOW}
        for ref in members
    ]
    binding_ids = [ei.validate_event_identity(row)["identity_id"] for row in bindings]
    operation = {
        "authority": authority, "op": "create", "episode_id": episode_id,
        "members": list(members), "creates_binding_ids": binding_ids,
        "canonical_event_kind": kind, "created_at": NOW,
    }
    return {"operation": operation, "bindings": bindings,
            "operation_id": operation_id, "episode_id": episode_id,
            "binding_ids": binding_ids}


def side_binding(telling_ref: str, episode_id: str, relation: str,
                 origin: str = "confirmed") -> dict:
    return {"telling_ref": telling_ref, "episode_id": episode_id,
            "relation": relation, "origin": origin,
            "source_ref": "sources/conversations/msg-identity.md",
            "created_at": NOW}


def founder_records() -> dict:
    """The whole fixture as one `episode_records` input.

    Five ``same`` tellings, one ``part_of``, one ``related``, one ``not_same``
    and one ``proposed`` — the five relations §2.2 defines plus the epistemic
    origin §2.3 says changes no drawing, all against ONE episode.
    """
    plan = create_plan(tuple(refs_of("same")), kind=FIXTURE["episode"]["canonical_event_kind"])
    episode_id = plan["episode_id"]
    extra = [
        side_binding(refs_of("part_of")[0], episode_id, "part_of"),
        side_binding(refs_of("related")[0], episode_id, "related"),
        side_binding(refs_of("not_same")[0], episode_id, "not_same"),
        side_binding(refs_of("proposed")[0], episode_id, "same", origin="proposed"),
    ]
    return {
        "operations": [ei.validate_episode_operation(plan["operation"])],
        "bindings": [ei.validate_event_identity(row)
                     for row in plan["bindings"] + extra],
        "episode_id": episode_id,
        "plan": plan,
    }


def records_input(records: dict, **overrides) -> dict:
    payload = {"operations": records["operations"], "bindings": records["bindings"]}
    payload.update(overrides)
    return payload


def derive(claims, **kwargs):
    kwargs.setdefault("now", NOW)
    index = {"version": ts.INDEX_VERSION, "claims": [dict(row) for row in claims]}
    return tt.derive_calculated_timeline(index, **kwargs)


def node_by_episode(result, episode_id: str) -> dict | None:
    for row in result.nodes:
        if row.get("episode_id") == episode_id:
            return row
    return None


def date_questions(result) -> list:
    """Every "when did this happen?" the queue would ask.

    ``precision_gap`` with ``requested_field: date`` is what an undated node
    mints — the exact question §1.2 says Play asks after the person already
    answered it somewhere else — so this is the measure the whole program is
    about, not the node count.
    """
    return [row for row in result.work_items
            if row.get("kind") == "precision_gap"
            and row.get("requested_field") == "date"]


# ==========================================================================
# §5.1 — grouping
# ==========================================================================


class GroupingTests(unittest.TestCase):
    """Five tellings, one node, one reconciled date (design §1, §5.1, §5.2)."""

    def setUp(self) -> None:
        self.records = founder_records()
        self.claims = all_claims()
        self.before = derive(self.claims)
        self.after = derive(self.claims, episode_records=records_input(self.records))

    def test_the_pre_binding_drawing_is_the_founders_own_diagnosis(self):
        """Every telling is its own node and the undated ones are unplaced —
        which is exactly the state §1 measured and the reason for the program."""
        self.assertEqual(len(self.before.nodes), FIXTURE["expected"]["nodes_before_binding"])
        self.assertIsNone(node_by_episode(self.before, self.records["episode_id"]))

    def test_five_tellings_become_one_node(self):
        node = node_by_episode(self.after, self.records["episode_id"])
        self.assertIsNotNone(node)
        self.assertEqual(node["telling_count"], FIXTURE["expected"]["same_tellings"])
        self.assertEqual(node["tellings"], sorted(refs_of("same")))
        self.assertEqual(len(self.after.nodes), FIXTURE["expected"]["nodes_after_binding"])

    def test_the_episode_node_is_an_episode_node(self):
        node = node_by_episode(self.after, self.records["episode_id"])
        self.assertEqual(node["node_kind"], efc.EPISODE_NODE_KIND)
        self.assertEqual(node["event_kind"], FIXTURE["episode"]["canonical_event_kind"])
        self.assertEqual(
            node["node_id"],
            efc.episode_node_id(
                canonical_event_kind=FIXTURE["episode"]["canonical_event_kind"],
                subject_keys=ef.EPISODE_SUBJECT_KEYS,
                episode_id=self.records["episode_id"],
            ),
        )

    def test_the_date_is_reconciled_over_the_union_of_the_tellings_claims(self):
        """§5.2: the one telling that carried a date dates all five, through
        `chronology.reconcile` and nothing else."""
        node = node_by_episode(self.after, self.records["episode_id"])
        value = chrono.from_dict(node["best_temporal_value"])
        self.assertEqual(value.best, FIXTURE["episode"]["stated_date"])
        self.assertEqual(value.basis, "stated")

    def test_every_former_node_id_is_published_in_node_aliases(self):
        """Law 5: an open session, a Mirror row and an old URL keep resolving."""
        node = node_by_episode(self.after, self.records["episode_id"])
        aliases = self.after.node_aliases
        self.assertTrue(aliases)
        for former, survivor in aliases.items():
            self.assertEqual(survivor, node["node_id"])
        for row in tellings("same"):
            if row["kind"] != "classifier":
                continue
            former = tp.derive_node_id(
                node_kind="event", event_kind=row["event_kind"],
                subject_refs=[row["subject"]], discriminator=row["telling_ref"],
            )
            self.assertIn(former, aliases)

    def test_the_identity_block_names_where_the_grouping_came_from(self):
        node = node_by_episode(self.after, self.records["episode_id"])
        self.assertEqual(node["identity_origins"], ["deterministic"])
        self.assertEqual(node["episode_id"], self.records["episode_id"])

    def test_a_node_nothing_bound_carries_no_identity_block(self):
        """Additive means absent, not empty: a vault that has never bound
        anything publishes exactly the nodes it published at v264."""
        untouched = [row for row in self.after.nodes
                     if row.get("event_kind") == "birth"]
        self.assertEqual(len(untouched), 1)
        for key in tp.CalculatedTimelineNode.__dataclass_fields__:
            if key in ("episode_id", "tellings", "telling_count", "identity_origins"):
                self.assertNotIn(key, untouched[0])

    def test_a_proposed_binding_changes_no_drawing(self):
        """§2.3: only the first three origins affect grouping. The proposal is
        RENDERED as a link and folds nothing — proven by the node the proposed
        telling still has to itself."""
        proposed_ref = refs_of("proposed")[0]
        episode_node = node_by_episode(self.after, self.records["episode_id"])
        self.assertNotIn(proposed_ref, episode_node["tellings"])
        own = [row for row in self.after.nodes
               if row.get("proposed_links")]
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]["proposed_links"][0]["telling_ref"], proposed_ref)
        self.assertEqual(own[0]["proposed_links"][0]["origin"], "proposed")
        self.assertEqual(
            [row["code"] for row in self.after.identity_diagnostics["findings"]
             if row["code"] == efc.DIAGNOSTIC_PROPOSAL_NOT_APPLIED],
            [efc.DIAGNOSTIC_PROPOSAL_NOT_APPLIED],
        )

    def test_a_related_binding_is_a_rendered_link_and_nothing_else(self):
        related_ref = refs_of("related")[0]
        rows = [row for row in self.after.nodes if row.get("related")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["related"][0]["telling_ref"], related_ref)
        self.assertNotIn(related_ref,
                         node_by_episode(self.after, self.records["episode_id"])["tellings"])
        # …and it keeps its own date. `related` means "same story, different
        # event", so the 2021 idea is still 2021.
        self.assertEqual(chrono.from_dict(rows[0]["best_temporal_value"]).best, "2021")

    def test_a_not_same_binding_draws_nothing(self):
        negative_ref = refs_of("not_same")[0]
        for row in self.after.nodes:
            self.assertNotIn(negative_ref, row.get("tellings") or ())
            for key in ("containments", "related", "proposed_links"):
                for link in row.get(key) or ():
                    self.assertNotEqual(link["telling_ref"], negative_ref)


class WhenIsAskedOnceTests(unittest.TestCase):
    """§1.2's consequence, reversed: Play stops asking what he already said."""

    def setUp(self) -> None:
        self.records = founder_records()
        self.claims = all_claims()
        self.before = derive(self.claims)
        self.after = derive(self.claims, episode_records=records_input(self.records))

    def test_every_undated_telling_asks_when_before_the_bind(self):
        self.assertEqual(len(date_questions(self.before)),
                         FIXTURE["expected"]["date_questions_before_binding"])
        self.assertEqual(len(self.before.diagnostics["unplaced"]),
                         FIXTURE["expected"]["unplaced_before_binding"])

    def test_binding_them_into_a_dated_episode_stops_asking(self):
        """The four undated Etherfuse occurrences are dated by the landmark
        that dated the fifth, so the queue stops asking WHEN about facts the
        person already placed — §1.2's consequence, reversed."""
        self.assertEqual(len(date_questions(self.after)),
                         FIXTURE["expected"]["date_questions_after_binding"])
        self.assertEqual(len(self.after.diagnostics["unplaced"]),
                         FIXTURE["expected"]["unplaced_after_binding"])

    def test_the_episode_itself_is_never_asked_when(self):
        node = node_by_episode(self.after, self.records["episode_id"])
        for item in date_questions(self.after):
            self.assertNotEqual(item.get("node_ref"), node["node_id"])

    def test_no_surviving_question_is_about_a_telling_the_bind_dated(self):
        """The founder's own sentence: Play must not ask "when did you start
        Etherfuse?" after he said May 2022."""
        surviving = {item.get("node_ref") for item in date_questions(self.after)}
        node = node_by_episode(self.after, self.records["episode_id"])
        self.assertNotIn(node["node_id"], surviving)
        for former in self.after.node_aliases:
            self.assertNotIn(former, surviving)


# ==========================================================================
# §5.1 — the era carve-out, untouched
# ==========================================================================


class EraCompositionTests(unittest.TestCase):
    """`event_ref`'s v247 era meaning is untouched (design §3.5, audit A2)."""

    def _era_claim(self) -> dict:
        return _claim(
            claim_type="date", subject_mention="I", event_kind="period_started",
            event_ref="era:" + "a" * 24, source="classification:college#999999999999",
            quote="College started in 1999.",
            temporal_value={"best": "1999", "earliest": "1999", "latest": "1999",
                            "granularity": "year", "basis": "stated",
                            "confidence": "certain"},
        )

    def test_an_era_bound_claim_folds_exactly_as_it_did_at_v264(self):
        claim = self._era_claim()
        plan = create_plan(("classification:college#999999999999",), kind="moment")
        without = derive([birth_claim(), claim])
        with_binding = derive(
            [birth_claim(), claim],
            episode_records={"operations": [ei.validate_episode_operation(plan["operation"])],
                             "bindings": [ei.validate_event_identity(row)
                                          for row in plan["bindings"]]},
        )
        self.assertEqual(
            [row["node_id"] for row in without.nodes],
            [row["node_id"] for row in with_binding.nodes],
        )
        self.assertIn("era:" + "a" * 24,
                      [row["node_id"] for row in with_binding.nodes])

    def test_the_binding_on_an_era_bound_claim_is_reported_not_obeyed(self):
        claim = self._era_claim()
        plan = create_plan(("classification:college#999999999999",), kind="moment")
        result = derive(
            [birth_claim(), claim],
            episode_records={"operations": [ei.validate_episode_operation(plan["operation"])],
                             "bindings": [ei.validate_event_identity(row)
                                          for row in plan["bindings"]]},
        )
        codes = [row["code"] for row in result.identity_diagnostics["findings"]]
        self.assertIn(efc.DIAGNOSTIC_BINDING_TO_ERA_CLAIM, codes)

    def test_a_telling_about_an_event_WITHIN_an_era_keeps_full_eligibility(self):
        """Audit F-pin 1's own failure case: never discard the second telling's
        episode eligibility merely because ANOTHER telling carried an era ref."""
        records = founder_records()
        claims = all_claims() + [self._era_claim()]
        result = derive(claims, episode_records=records_input(records))
        node = node_by_episode(result, records["episode_id"])
        self.assertEqual(node["telling_count"], FIXTURE["expected"]["same_tellings"])


# ==========================================================================
# §5.4 — the refusals, each proven in both directions
# ==========================================================================


class RefusalTests(unittest.TestCase):

    def _two_same_bindings(self) -> list:
        first = create_plan((refs_of("same")[0],), kind="job")
        second = create_plan((refs_of("same")[0],), kind="moment",
                             authority="human", origin="confirmed")
        return [ei.validate_event_identity(row)
                for row in first["bindings"] + second["bindings"]]

    def test_two_active_same_bindings_for_one_telling_are_identity_conflict(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            derive(all_claims(), episode_records=self._two_same_bindings())
        self.assertEqual(caught.exception.code, efc.REFUSAL_IDENTITY_CONFLICT)

    def test_the_same_pair_superseded_is_no_conflict_at_all(self):
        """The neighbouring state that must NOT trip the guard: re-deciding is
        a new record naming what it supersedes (Law 2)."""
        rows = self._two_same_bindings()
        rows[1] = ei.validate_event_identity(
            {**rows[1], "supersedes": rows[0]["identity_id"]}
        )
        result = derive(all_claims(), episode_records=rows)
        # The SECOND decision is the live one, and the first is simply gone —
        # not out-voted, superseded.
        node = node_by_episode(result, rows[1]["episode_id"])
        self.assertIsNotNone(node)
        self.assertEqual(node["tellings"], [refs_of("same")[0]])
        self.assertIsNone(node_by_episode(result, rows[0]["episode_id"]))

    def test_same_here_and_not_same_there_is_NOT_a_conflict(self):
        """The narrow reading I0 pinned (#296 finding 1). §5.4 read literally
        would refuse the five-answer model §6.1 requires: a telling carries
        `same` to one episode and `not_same` to every episode already
        rejected. If this raised, the product could not exist."""
        records = founder_records()
        ref = refs_of("same")[0]
        other = create_plan((refs_of("not_same")[0],), kind="moment")
        rows = list(records["bindings"]) + [
            ei.validate_event_identity(
                side_binding(ref, other["episode_id"], "not_same")
            )
        ]
        result = derive(all_claims(), episode_records=records_input(records, bindings=rows))
        self.assertEqual(
            node_by_episode(result, records["episode_id"])["telling_count"],
            FIXTURE["expected"]["same_tellings"],
        )

    def test_a_dormant_binding_is_reported_and_ignored(self):
        """A retracted claim is not a bug in the binding (§3.3 lifecycle)."""
        records = founder_records()
        result = derive([birth_claim()], episode_records=records_input(records))
        codes = [row["code"] for row in result.identity_diagnostics["findings"]]
        self.assertEqual(set(codes), {efc.DIAGNOSTIC_DORMANT_BINDING})
        self.assertEqual(len(result.nodes), 1)

    def test_a_misspelled_input_key_is_a_refusal_not_a_silent_no_op(self):
        with self.assertRaises(tc.TemporalContractError) as caught:
            derive(all_claims(), episode_records={"binding": []})
        self.assertEqual(caught.exception.code, "identity_input_unknown_key")


class EnvelopeRefusalTests(unittest.TestCase):
    """§3.2/G4 — an incomplete envelope is a loud refusal from the LOADER."""

    def _vault(self) -> Path:
        root = root_parent_tmp(self, ROOT, prefix="i1-envelope-")
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "sources").mkdir(parents=True, exist_ok=True)
        return root

    def test_an_envelope_whose_bindings_are_missing_refuses_to_load(self):
        root = self._vault()
        plan = create_plan(tuple(refs_of("same")), kind="job")
        ei.file_episode_operation(root, **plan["operation"])
        with self.assertRaises(tc.TemporalContractError) as caught:
            ef.load_episode_records(root)
        self.assertEqual(caught.exception.code, ef.REFUSAL_ENVELOPE_INCOMPLETE)

    def test_the_complete_envelope_loads(self):
        """The neighbouring state: the same envelope WITH its bindings."""
        root = self._vault()
        plan = create_plan(tuple(refs_of("same")), kind="job")
        ei.file_operation_envelope(root, operation=plan["operation"],
                                   bindings=plan["bindings"])
        loaded = ef.load_episode_records(root)
        self.assertEqual(len(loaded["operations"]), 1)
        self.assertEqual(len(loaded["bindings"]), len(refs_of("same")))


# ==========================================================================
# §2.2 — entailment, computed and never stored
# ==========================================================================


class EntailmentTests(unittest.TestCase):

    def test_same_and_not_same_entail_the_pair(self):
        records = founder_records()
        result = derive(all_claims(), episode_records=records_input(records))
        pairs = result.identity_diagnostics["entailed_not_same"]
        self.assertEqual(len(pairs), FIXTURE["expected"]["entailed_not_same_pairs"])
        negative = refs_of("not_same")[0]
        for member in refs_of("same"):
            self.assertIn(sorted([member, negative]), pairs)

    def test_retracting_either_premise_removes_the_entailed_pair(self):
        """The reason it is never stored: a stored closure would leave a
        permanent phantom negative behind the record that was withdrawn."""
        records = founder_records()
        without_negative = [row for row in records["bindings"]
                            if row["relation"] != "not_same"]
        result = derive(all_claims(),
                        episode_records=records_input(records, bindings=without_negative))
        self.assertEqual(result.identity_diagnostics["entailed_not_same"], [])

    def test_the_fold_writes_nothing_while_entailing(self):
        root = root_parent_tmp(self, ROOT, prefix="i1-entail-")
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "sources").mkdir(parents=True, exist_ok=True)
        records = founder_records()
        before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        derive(all_claims(), episode_records=records_input(records))
        after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        self.assertEqual(before, after)


# ==========================================================================
# §5.3 — containment's inherited value
# ==========================================================================


class ContainmentTests(unittest.TestCase):

    def setUp(self) -> None:
        self.records = founder_records()
        self.result = derive(all_claims(),
                             episode_records=records_input(self.records))
        self.member = self._member(self.result)

    def _member(self, result) -> dict:
        ref = refs_of("part_of")[0]
        for row in result.nodes:
            for link in row.get("containments") or ():
                if link["telling_ref"] == ref:
                    return row
        raise AssertionError("no contained member in the projection")

    def test_a_contained_member_gets_the_episodes_span_as_a_POSSIBILITY(self):
        self.assertIsNone(self.member.get("best_temporal_value"))
        possible = chrono.from_dict(self.member["possible_temporal_value"])
        self.assertEqual(possible.best, FIXTURE["episode"]["stated_date"])
        self.assertEqual(possible.confidence, "inferred")

    def test_it_is_never_an_anchor(self):
        possible = chrono.from_dict(self.member["possible_temporal_value"])
        self.assertEqual(possible.anchors, ())

    def test_it_is_never_narrower_than_the_span(self):
        node = node_by_episode(self.result, self.records["episode_id"])
        episode = chrono.from_dict(node["best_temporal_value"])
        possible = chrono.from_dict(self.member["possible_temporal_value"])
        self.assertEqual((possible.earliest, possible.latest),
                         (episode.earliest, episode.latest))

    def test_it_never_overrides_a_value_the_person_gave(self):
        """The structural half: `possible_outer_range` reads
        `member_value is None` and nothing else, so there is no branch in
        which a stated value loses. Proved through the fold by dating the
        member and watching the possibility disappear."""
        row = dict(tellings("part_of")[0])
        row["dated"] = "2023-09"
        claims = [birth_claim()] + [
            telling_claim(row if item["role"] == "part_of" else item)
            for item in tellings()
        ]
        result = derive(claims, episode_records=records_input(self.records))
        member = self._member(result)
        self.assertIsNone(member.get("possible_temporal_value"))
        self.assertEqual(chrono.from_dict(member["best_temporal_value"]).best, "2023-09")

    def test_it_never_suppresses_the_members_own_precision_question(self):
        """§5.3: the probe just gets better, it does not go away. `placed` is
        untouched by a containment, so the WHEN item is minted exactly as it
        was before the containment existed."""
        asked = {item.get("node_ref") for item in date_questions(self.result)}
        self.assertIn(self.member["node_id"], asked)
        self.assertIn("{episode}", efc.CONTAINMENT_PROBE_TEXT)

    def test_two_containing_episodes_are_no_pick_at_all(self):
        """An ambiguity is a Mirror row for I3, never a guess made here.

        C2 refuses this state at WRITE time — a telling holds one grouping
        binding or none (`validate_identity_set`) — and the fold refuses to
        choose anyway, because "the writer would have stopped it" is not a
        reason for a reader to guess.
        """
        elsewhere = create_plan((refs_of("related")[0],), kind="moment")
        rows = list(self.records["bindings"]) + [
            ei.validate_event_identity(elsewhere["bindings"][0]),
            ei.validate_event_identity(
                side_binding(refs_of("part_of")[0], elsewhere["episode_id"], "part_of")
            ),
        ]
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_identity_set(rows)
        self.assertEqual(caught.exception.code, "identity_conflict")

        result = derive(all_claims(), episode_records=records_input(
            self.records, bindings=rows))
        member = self._member(result)
        self.assertIsNone(member.get("possible_temporal_value"))
        self.assertEqual(len(member["containments"]), 2)

    def test_era_membership_alone_still_implies_no_date(self):
        """Unchanged from v247: a frame membership is a receipt ABOUT a node,
        never a bound on it. The contained member sits in the owner's 40s and
        is still undated, and the containment is the only thing that gave it
        a possible range."""
        member = self.member
        frames = [row for row in self.result.memberships
                  if row.get("member_node_id") == member["node_id"]]
        self.assertIsNone(member.get("best_temporal_value"))
        self.assertIsNotNone(member.get("possible_temporal_value"))
        for row in frames:
            self.assertNotIn("best_temporal_value", row)


# ==========================================================================
# §5.6 — the two determinism properties
# ==========================================================================


class DeterminismTests(unittest.TestCase):

    def test_a_fixed_set_of_receipts_folds_byte_identically_under_any_order(self):
        records = founder_records()
        claims = all_claims()
        reference = tt.structural_signature(
            derive(claims, episode_records=records_input(records))
        )
        for permutation in (
            (list(reversed(claims)), list(records["bindings"])),
            (claims, list(reversed(records["bindings"]))),
            (list(reversed(claims)), list(reversed(records["bindings"]))),
            (claims[3:] + claims[:3], records["bindings"][2:] + records["bindings"][:2]),
        ):
            permuted_claims, permuted_bindings = permutation
            other = tt.structural_signature(
                derive(permuted_claims,
                       episode_records=records_input(records, bindings=permuted_bindings))
            )
            self.assertEqual(
                json.dumps(reference, sort_keys=True),
                json.dumps(other, sort_keys=True),
            )

    def test_the_grouping_fingerprint_is_the_permutation_oracle(self):
        records = founder_records()
        index = ef.claim_telling_index(all_claims())
        active = efc.active_binding_index(
            [ef._enriched(row, ef.episode_index(records["operations"], records["bindings"]))
             for row in records["bindings"]]
        )
        one = efc.fold_grouping(all_claims(), {"tellings": [
            {"telling_ref": ref, "claim_ids": [cid], "status": "active"}
            for cid, ref in sorted(index.items())
        ]}, active)
        two = efc.fold_grouping(list(reversed(all_claims())), {"tellings": [
            {"telling_ref": ref, "claim_ids": [cid], "status": "active"}
            for cid, ref in sorted(index.items(), reverse=True)
        ]}, active)
        self.assertEqual(efc.grouping_fingerprint(one), efc.grouping_fingerprint(two))


class LinkOrderTests(unittest.TestCase):
    """The adapter's own output order, asserted where it is DECIDED.

    `temporal_projection` sorts the link rows again at validation, so the two
    guards overlap — which is why this test reads `EpisodeIdentity.node_block`
    directly rather than the published node. A property proved only by its
    downstream twin is a property nobody is holding: delete the sort here and
    the projection still looks right, and the next reader of `node_block`
    (I2's dry-run, I3's Play flow, the platform card) gets records in
    whatever order the caller happened to hand them over.
    """

    #: Two episode ids whose BINDING DIGESTS sort the opposite way to the
    #: episode id itself. Found by search rather than chosen: a guard against
    #: an ordering can only fire on a case where the two orderings actually
    #: disagree, and a fixture that happened to agree would pass with the sort
    #: deleted — a test proving nothing.
    LOW_EPISODE = "episode:ba6bc8115c784af3b6b5211b"
    HIGH_EPISODE = "episode:ee420d7cc1d2d38d5b0071f6"

    def test_one_tellings_links_come_out_in_key_order_not_digest_order(self):
        """`active_binding_index` orders a telling's rows by ``identity_id``,
        which is a digest and therefore arbitrary. `node_block` publishes them
        in KEY order, so two hosts assembling the same records publish the same
        bytes without either depending on what a hash happened to do."""
        ref = refs_of("part_of")[0]
        rows = [
            ei.validate_event_identity(side_binding(ref, self.LOW_EPISODE, "related")),
            ei.validate_event_identity(side_binding(ref, self.HIGH_EPISODE, "related")),
        ]
        identity = ef.EpisodeIdentity(all_claims(), rows)
        self.assertEqual(
            [row["episode_id"] for row in identity.active[ref]],
            [self.HIGH_EPISODE, self.LOW_EPISODE],
            "precondition: C3 hands these two over in digest order, which is "
            "the reverse of key order",
        )
        published = identity.node_block("node:" + "0" * 24, all_claims())["related"]
        self.assertEqual([row["episode_id"] for row in published],
                         [self.LOW_EPISODE, self.HIGH_EPISODE])

    def test_the_link_rows_come_out_sorted_whatever_order_they_arrived_in(self):
        records = founder_records()
        claims = all_claims()
        forward = ef.EpisodeIdentity(claims, records_input(records))
        backward = ef.EpisodeIdentity(
            claims, records_input(records, bindings=list(reversed(records["bindings"])))
        )
        for node_id in sorted(forward.episode_of_node) + [
            row["telling_ref"] for row in tellings("part_of", "related", "proposed")
        ]:
            self.assertEqual(
                forward.node_block(node_id, claims),
                backward.node_block(node_id, claims),
            )
        block = forward.node_block(
            forward.node_of_episode[records["episode_id"]], claims
        )
        for key in ("containments", "related", "proposed_links"):
            rows = block.get(key) or []
            self.assertEqual(
                rows, sorted(rows, key=lambda row: (row["telling_ref"],
                                                    row["episode_id"],
                                                    row["relation"])),
            )


class SplitRestoresTheDrawingTests(unittest.TestCase):
    """§5.5 at the RECORD level — no file is deleted, a record supersedes."""

    def test_superseding_every_same_binding_restores_the_prior_drawing(self):
        records = founder_records()
        claims = all_claims()
        before = tt.structural_signature(derive(claims))
        grouped = [row for row in records["bindings"]
                   if row["relation"] == "same" and row["origin"] == "deterministic"]
        departures = []
        for row in grouped:
            departure = ei.validate_event_identity({
                "telling_ref": row["telling_ref"],
                "episode_id": row["episode_id"],
                "relation": ei.SPLIT_DEPARTURE_RELATION,
                "origin": "confirmed",
                "supersedes": row["identity_id"],
                "source_ref": "sources/conversations/msg-split.md",
                "created_at": NOW,
            })
            departures.append(departure)
        survivors = [row for row in records["bindings"]
                     if row["relation"] not in ("same",) or row["origin"] == "proposed"]
        after = derive(claims, episode_records=records_input(
            records, bindings=survivors + departures))
        self.assertEqual(
            [row["node_id"] for row in json.loads(json.dumps(before))["nodes"]],
            [row["node_id"] for row in after.to_dict()["nodes"]],
        )
        self.assertEqual(len(date_questions(derive(claims))), len(date_questions(after)))


# ==========================================================================
# CERT-11, the OSS half (§7)
# ==========================================================================


class Cert11Tests(unittest.TestCase):
    """Delete the layer; the drawing returns. Then: sources alone rebuild it."""

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="i1-cert11-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        self.claims = all_claims()
        self.plan = create_plan(tuple(refs_of("same")), kind="job")
        ei.file_operation_envelope(self.root, operation=self.plan["operation"],
                                   bindings=self.plan["bindings"])

    def _signature(self, records) -> str:
        return json.dumps(
            tt.structural_signature(derive(self.claims, episode_records=records)),
            sort_keys=True,
        )

    def _without_identity_keys(self, signature: str) -> str:
        payload = json.loads(signature)
        for key in ef.IDENTITY_ENVELOPE_KEYS:
            payload.pop(key, None)
        return json.dumps(payload, sort_keys=True)

    def test_the_layer_applies_before_it_is_deleted(self):
        loaded = ef.load_episode_records(self.root)
        result = derive(self.claims, episode_records=loaded)
        self.assertEqual(
            node_by_episode(result, self.plan["episode_id"])["telling_count"],
            len(refs_of("same")),
        )

    def test_deleting_the_state_layer_returns_the_pre_binding_projection(self):
        pristine = self._signature(())
        shutil.rmtree(self.root / ei.IDENTITY_STATE_DIR)
        manifest = self.root / ei.TELLING_MANIFEST_FILE
        if manifest.exists():
            manifest.unlink()
        loaded = ef.load_episode_records(self.root)
        self.assertEqual(loaded["bindings"], [])
        self.assertEqual(
            self._without_identity_keys(pristine),
            self._without_identity_keys(self._signature(loaded)),
        )

    def test_the_sources_side_records_alone_rebuild_the_same_partition(self):
        """§5.8 row 10 and §13.2's second promise. The person confirms every
        deterministic membership and adopts the episode; then every byte under
        `state/` is deleted and the partition is still exactly what she said."""
        ei.file_adopt_envelope(
            self.root,
            episode_id=self.plan["episode_id"],
            creation_canonical_inputs=self.plan["operation"].get("canonical_inputs")
            or ei.validate_episode_operation(self.plan["operation"])["canonical_inputs"],
            canonical_event_kind="job",
            source_ref="sources/conversations/msg-adopt.md",
        )
        for row in self.plan["bindings"]:
            validated = ei.validate_event_identity(row)
            ei.file_event_identity(self.root, **{
                "telling_ref": validated["telling_ref"],
                "episode_id": validated["episode_id"],
                "relation": "same",
                "origin": "confirmed",
                "supersedes": validated["identity_id"],
                "source_ref": "sources/conversations/msg-adopt.md",
                "created_at": NOW,
            })
        both = derive(self.claims, episode_records=ef.load_episode_records(self.root))
        shutil.rmtree(self.root / ei.IDENTITY_STATE_DIR)
        sources_only = derive(self.claims,
                              episode_records=ef.load_episode_records(self.root))
        self.assertEqual(
            node_by_episode(both, self.plan["episode_id"])["tellings"],
            node_by_episode(sources_only, self.plan["episode_id"])["tellings"],
        )
        self.assertEqual(
            node_by_episode(both, self.plan["episode_id"])["node_id"],
            node_by_episode(sources_only, self.plan["episode_id"])["node_id"],
        )

    def test_a_binding_record_never_modifies_a_claim_or_a_telling(self):
        """§13.1: their bytes and ids are identical before and after."""
        before = json.dumps([dict(row) for row in self.claims], sort_keys=True)
        derive(self.claims, episode_records=ef.load_episode_records(self.root))
        after = json.dumps([dict(row) for row in self.claims], sort_keys=True)
        self.assertEqual(before, after)


# ==========================================================================
# Versions and the frozen key lists
# ==========================================================================


class VersionTests(unittest.TestCase):

    def test_the_calculation_rule_version_is_five(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:5")

    def test_the_projection_schema_version_did_not_move(self):
        """Every §3.5 field is ADDITIVE, so a v2 reader reads a v2 payload."""
        self.assertEqual(tp.PROJECTION_SCHEMA_VERSION, 2)

    def test_the_three_frozen_key_lists_are_byte_identical_to_v264(self):
        self.assertEqual(
            tc.CLAIM_IDENTITY_KEYS,
            ("claim_type", "subject_key", "event_kind", "temporal_identity",
             "source_ref", "extractor_version"),
        )
        self.assertEqual(
            tp.NODE_IDENTITY_KEYS,
            ("node_kind", "event_kind", "subject_keys", "discriminator"),
        )
        self.assertEqual(
            tp.WORK_ITEM_IDENTITY_KEYS,
            ("kind", "subject_key", "event_key", "requested_field"),
        )

    def test_the_identity_rule_version_still_has_exactly_one_home(self):
        self.assertEqual(tt.CalculatedTimeline().identity_rule_version,
                         efc.IDENTITY_RULE_VERSION)


class NodeSchemaRefusalTests(unittest.TestCase):
    """The additive block's own guards, each proven in both directions."""

    def _node(self, **extra) -> dict:
        payload = {
            "node_id": "node:" + "a" * 24, "node_kind": "episode",
            "input_claim_refs": ["claim:" + "b" * 24],
            "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
        }
        payload.update(extra)
        return payload

    def test_an_episode_block_on_a_non_episode_node_is_refused(self):
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(
                self._node(node_kind="event", episode_id="episode:" + "c" * 24,
                           tellings=[], telling_count=0)
            )
        self.assertEqual(caught.exception.code, "episode_block_on_non_episode_node")

    def test_the_same_block_on_an_episode_node_is_accepted(self):
        row = tp.validate_calculated_timeline_node(
            self._node(episode_id="episode:" + "c" * 24,
                       tellings=["landmark:entry-x"], telling_count=1)
        )
        self.assertEqual(row["telling_count"], 1)

    def test_a_telling_count_that_disagrees_is_refused(self):
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(
                self._node(episode_id="episode:" + "c" * 24,
                           tellings=["landmark:entry-x"], telling_count=4)
            )
        self.assertEqual(caught.exception.code, "telling_count_disagrees")

    def test_a_link_naming_no_episode_is_refused(self):
        with self.assertRaises(tp.TimelineNodeError) as caught:
            tp.validate_calculated_timeline_node(
                self._node(related=[{"telling_ref": "landmark:entry-x"}])
            )
        self.assertEqual(caught.exception.code, "identity_link_malformed")

    def test_links_are_sorted_so_two_hosts_publish_the_same_bytes(self):
        rows = [
            {"telling_ref": "landmark:entry-z", "episode_id": "episode:" + "d" * 24},
            {"telling_ref": "landmark:entry-a", "episode_id": "episode:" + "c" * 24},
        ]
        forward = tp.validate_calculated_timeline_node(self._node(related=rows))
        backward = tp.validate_calculated_timeline_node(
            self._node(related=list(reversed(rows)))
        )
        self.assertEqual(forward["related"], backward["related"])
        self.assertEqual(forward["related"][0]["telling_ref"], "landmark:entry-a")


# ==========================================================================
# §3.1 — the extractors declare their tellings (C1's named gap, closed)
# ==========================================================================


class DeclaredTellingsTests(unittest.TestCase):
    """`declare_tellings()` wired into both live extractors (I0 finding 2).

    C1 shipped the call and named the gap: no extractor declared a document
    revision, the classifier's claims cite the CLASSIFICATION's revision — which
    moves whenever the model rewords a title — so a rewording and a human
    source correction were indistinguishable and the manifest conservatively
    re-keyed nothing. I1 wires the call in: the classifier declares the STORY's
    own revision and the recorder declares the promoted record's, and where a
    revision is genuinely undeclarable the conservative behavior is unchanged.
    """

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="i1-declare-")
        (self.root / "state" / "classifications").mkdir(parents=True, exist_ok=True)
        (self.root / "sources" / "stories").mkdir(parents=True, exist_ok=True)

    # -- helpers ---------------------------------------------------------

    def _story(self, stem: str, text: str) -> tuple:
        relative = f"sources/stories/{stem}.md"
        body = f"{text}\n"
        frontmatter = {
            "title": stem, "type": "story", "source_id": f"story:{stem}",
            "source_path": relative, "content_sha256": ts.payload_sha256(body),
        }
        (self.root / relative).write_text(
            f"{ts.format_frontmatter(frontmatter)}\n\n{body}", encoding="utf-8"
        )
        return relative, f"sha256:{frontmatter['content_sha256']}"

    def _classify(self, stem: str, source_path: str, events: list) -> None:
        payload = {"source_path": source_path, "people": [], "places": [],
                   "time_periods": [], "themes": [], "events": events}
        (self.root / "state" / "classifications" / f"{stem}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _migrate(self) -> dict:
        import classifier_claims as cc  # noqa: PLC0415

        return cc.migrate_classifier_moments(
            self.root,
            classifications_dir=self.root / "state" / "classifications",
            dry_run=False, now=NOW,
        )

    def _receipts(self) -> list:
        receipts, _unreadable = ts.load_receipts(self.root)
        return receipts

    # -- the classifier --------------------------------------------------

    def test_the_classifier_declares_its_tellings_and_the_STORYS_revision(self):
        import classifier_claims as cc  # noqa: PLC0415

        relative, story_revision = self._story("etherfuse", "We started Etherfuse.")
        event = {"title": "Started Etherfuse", "description": "The company began.",
                 "when_hint": None, "anchor": None, "date": None}
        self._classify("etherfuse", relative, [event])
        self._migrate()

        receipts = self._receipts()
        self.assertEqual(len(receipts), 1)
        block = receipts[0].extractor
        expected_ref = cc.event_source_id("etherfuse", event)
        self.assertEqual(list(block[ei.TELLING_KEYS_FIELD].values()), [expected_ref])
        self.assertEqual(block[ei.DOCUMENT_REVISION_FIELD], story_revision)
        # …and it is NOT the classification's own revision, which is the whole
        # point: that one moves every time the model rewords a title.
        classification = json.loads(
            (self.root / "state" / "classifications" / "etherfuse.json").read_text("utf-8")
        )
        self.assertNotEqual(story_revision, cc.classification_revision(classification))

    def test_an_undeclarable_story_revision_stays_conservative(self):
        """The neighbouring state, and the reason the gap was named rather than
        guessed at: a source whose bytes have drifted under the claims that
        cite it declares nothing, and the manifest keeps refusing to re-key."""
        import classifier_claims as cc  # noqa: PLC0415

        relative, _revision = self._story("drifted", "The original words.")
        path = self.root / relative
        path.write_text(path.read_text("utf-8").replace("original", "edited"),
                        encoding="utf-8")
        self.assertIsNone(cc.document_revision(self.root, relative))
        self.assertIsNone(cc.document_revision(self.root, "sources/stories/absent.md"))

    def test_the_declaration_lets_the_manifest_tell_a_rewording_from_a_correction(self):
        """The gap, closed. The story does not change a byte; the model
        rewords the title. Before I1 that read as an undeclared revision and
        re-keyed nothing; now the manifest reaches the EVIDENCE rung and says
        `telling_rekey` because the words are all that agree."""
        relative, _revision = self._story("gap", "One thing happened.")
        self._classify("gap", relative, [
            {"title": "A thing", "description": "It happened.",
             "when_hint": None, "anchor": None, "date": None}
        ])
        self._migrate()
        self._classify("gap", relative, [
            {"title": "The thing", "description": "It happened, once.",
             "when_hint": None, "anchor": None, "date": None}
        ])
        self._migrate()

        manifest = ei.build_telling_manifest(self.root)
        findings = {row["finding"] for row in manifest["diagnostics"]}
        self.assertNotIn(ei.UNDECLARED_DOCUMENT_REVISION, findings)
        retired = [row for row in manifest["tellings"] if row["status"] == "retired"]
        self.assertEqual(len(retired), 1)
        self.assertEqual(retired[0]["rekey_case"], "reworded")
        self.assertEqual(retired[0]["document_revision"], _revision)

    def test_a_source_correction_is_told_apart_from_a_rewording(self):
        """The other half of the same fact: when the STORY changes, the
        manifest says `telling_source_corrected` and carries nothing across."""
        relative, first = self._story("corrected", "One thing happened.")
        self._classify("corrected", relative, [
            {"title": "A thing", "description": "It happened.",
             "when_hint": None, "anchor": None, "date": None}
        ])
        self._migrate()
        _relative, second = self._story("corrected", "One thing happened, in Tucson.")
        self._classify("corrected", relative, [
            {"title": "A thing in Tucson", "description": "It happened in Tucson.",
             "when_hint": None, "anchor": None, "date": None}
        ])
        self._migrate()
        self.assertNotEqual(first, second)

        manifest = ei.build_telling_manifest(self.root)
        findings = {row["finding"] for row in manifest["diagnostics"]}
        self.assertIn(ei.CORRECTION_DIAGNOSTIC, findings)
        self.assertNotIn(ei.UNDECLARED_DOCUMENT_REVISION, findings)

    # -- the recorder ----------------------------------------------------

    def test_the_recorder_declares_its_telling_its_revision_and_its_entry_id(self):
        import landmark_projection as lp  # noqa: PLC0415

        filed = lp.file_landmark_record(
            self.root, "work",
            {"label": "Etherfuse", "date": "2022-05", "domain": "work"},
            ordinal=1, now=NOW,
        )
        block = self._receipts()[0].extractor
        source_id = filed["source_ref"].source_id
        entry_id = source_id.partition(":")[2]
        self.assertEqual(set(block[ei.TELLING_KEYS_FIELD].values()),
                         {ei.landmark_telling_ref(entry_id)})
        self.assertEqual(block[ei.DOCUMENT_REVISION_FIELD], filed["source_ref"].revision)
        self.assertEqual(block[ei.RECORDER_EVENT_ID_FIELD], entry_id)

    def test_the_declared_ref_is_the_one_the_manifest_and_the_fold_agree_on(self):
        """One mint, read by both — the manifest row and the fold's own
        claim→telling map are the same string or the binding lands nowhere."""
        import landmark_projection as lp  # noqa: PLC0415

        filed = lp.file_landmark_record(
            self.root, "work",
            {"label": "Etherfuse", "date": "2022-05", "domain": "work"},
            ordinal=1, now=NOW,
        )
        manifest = ei.build_telling_manifest(self.root)
        refs = {row["telling_ref"] for row in manifest["tellings"]}
        folded = set(ef.claim_telling_index(filed["claims"]).values())
        self.assertEqual(refs, folded)


if __name__ == "__main__":
    unittest.main()
