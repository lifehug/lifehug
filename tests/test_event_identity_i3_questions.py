"""Event identity I3 — the questions.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 —
§6.1 (`same_event`'s five answers), §6.3 (`possible_overmerge`'s four),
§5.5 (the split rules table), §6.4 (the listener leaf), and the §13.3/§13.4
promises. I0 (`event_identity.py`, `episode_fold_contract.py`,
`episode_routing_contract.py`) settled what a record MEANS; I1
(`episode_fold.py`) taught the fold to apply one; I2 (`episode_binder.py`)
taught the substrate to DECIDE one, pairwise, as data. This phase is the
first thing a PERSON'S answer reaches.

Every negative below was run against a build with its guard removed and SEEN
failing first; the evidence table is in the PR body. Synthetic data only;
nothing here reads ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import cross_dating  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import event_identity as ei  # noqa: E402
import general_listener as gl  # noqa: E402
import identity_questions as iq  # noqa: E402
import mirror_work as mw  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-30T09:00:00Z"
LATER = "2027-01-01T00:00:00Z"

TELLING_A = "classification:story-a#aaaa1111aaaa"
TELLING_B = "classification:story-b#bbbb2222bbbb"
TELLING_C = "classification:story-c#cccc3333cccc"


def _vault(case: unittest.TestCase, prefix: str) -> Path:
    root = root_parent_tmp(case, ROOT, prefix=prefix)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _create_episode(root: Path, members: list, *, authority: str = "deterministic") -> str:
    """One episode, existing on disk, over ``members`` (sorted)."""
    members = sorted(members)
    operation_id = ei.operation_digest(
        authority=authority, op="create", rule_version=ei.IDENTITY_RULE_VERSION,
        member_refs=members,
    )
    episode_id = ei.episode_id_for(operation_id)
    bindings = []
    ids = []
    for ref in members:
        ids.append(ei.binding_digest(
            telling_ref=ref, episode_id=episode_id,
            relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
        ))
        bindings.append({
            "telling_ref": ref, "episode_id": episode_id,
            "relation": efc.GROUPING_RELATION, "origin": authority,
            "rule_version": ei.IDENTITY_RULE_VERSION, "created_at": NOW,
        })
    ei.file_operation_envelope(
        root,
        operation={
            "authority": authority, "op": "create", "rule_version": ei.IDENTITY_RULE_VERSION,
            "members": members, "creates_binding_ids": ids, "created_at": NOW,
        },
        bindings=bindings,
    )
    return episode_id


# ==========================================================================
# §1. The two kinds are registered — replacing PR #299's absence guard
# ==========================================================================


class KindRegistrationTests(unittest.TestCase):
    def test_the_two_new_kinds_are_now_registered_in_work_item_kinds(self):
        """I3 owns the probe, the five answers and the filing — the absence
        `test_event_identity_i2_binder.py` asserted at I2 becomes a positive
        registration now that something can file an answer."""
        self.assertIn(eb.SAME_EVENT_KIND, tp.WORK_ITEM_KINDS)
        self.assertIn(eb.POSSIBLE_OVERMERGE_KIND, tp.WORK_ITEM_KINDS)
        self.assertEqual(eb.SAME_EVENT_KIND, "same_event")
        self.assertIs(eb.POSSIBLE_OVERMERGE_KIND, erc.POSSIBLE_OVERMERGE_KIND)

    def test_the_local_play_stage_kind_list_stays_in_sync(self):
        """`timeline_interaction.WORK_ITEM_KINDS` names itself "the whole of"
        `temporal_projection.WORK_ITEM_KINDS` — a claim worth checking."""
        self.assertEqual(set(ti.WORK_ITEM_KINDS), set(tp.WORK_ITEM_KINDS))

    def test_both_kinds_have_a_probe(self):
        for kind in (eb.SAME_EVENT_KIND, eb.POSSIBLE_OVERMERGE_KIND):
            self.assertIn(kind, ti.WORK_ITEM_PROBES)
            spec = ti.WORK_ITEM_PROBES[kind]
            self.assertIn("text", spec)
            self.assertIn("step", spec)

    def test_both_kinds_have_value_scoring_beside_the_existing_ones(self):
        """§4.1: identity pairs enter the EXISTING value scoring, never a
        priority of their own — so both kinds need the same tables the five
        siblings have."""
        for kind in (eb.SAME_EVENT_KIND, eb.POSSIBLE_OVERMERGE_KIND):
            self.assertIn(kind, tt.WORK_ITEM_VALUE_DEFAULTS)
            self.assertIn(kind, tt.SURFACES_BY_KIND)
            self.assertIn(kind, tt.WORK_ITEM_PRECEDENCE)

    def test_precedence_sits_just_below_contradiction(self):
        order = tt.WORK_ITEM_PRECEDENCE
        contradiction_index = order.index("contradiction")
        for kind in (eb.SAME_EVENT_KIND, eb.POSSIBLE_OVERMERGE_KIND):
            self.assertGreater(order.index(kind), contradiction_index)
        # ...and still above the routine-gap kinds.
        for kind in (eb.SAME_EVENT_KIND, eb.POSSIBLE_OVERMERGE_KIND):
            self.assertLess(order.index(kind), order.index("place_ambiguous"))

    def test_both_kinds_are_mirror_allowlisted(self):
        """§6.3: possible_overmerge is Mirror-allowlisted with Play, and every
        actionable Mirror row has Play now."""
        self.assertIn(eb.SAME_EVENT_KIND, mw.MIRROR_WORK_ITEM_KINDS)
        self.assertIn(eb.POSSIBLE_OVERMERGE_KIND, mw.MIRROR_WORK_ITEM_KINDS)

    def test_a_same_event_work_item_validates_and_scores(self):
        item = tp.validate_temporal_work_item({
            "kind": "same_event", "event_ref": "classification:a#1|episode:" + "a" * 24,
            "allowed_surfaces": list(tt.work_item_surfaces("same_event")),
            "system_value": 0.4,
        }, now=NOW)
        self.assertEqual(item["kind"], "same_event")
        self.assertIn("timeline", item["allowed_surfaces"])
        self.assertIn("mirror", item["allowed_surfaces"])
        self.assertIn("daily_question", item["allowed_surfaces"])

    def test_a_possible_overmerge_work_item_validates_and_scores(self):
        item = tp.validate_temporal_work_item({
            "kind": "possible_overmerge", "event_ref": "possible_overmerge:" + "b" * 24,
            "allowed_surfaces": list(tt.work_item_surfaces("possible_overmerge")),
            "system_value": 0.6,
        }, now=NOW)
        self.assertEqual(item["kind"], "possible_overmerge")


# ==========================================================================
# §2. Generation — episode_binder's outputs become work items
# ==========================================================================


class GenerationTests(unittest.TestCase):
    def test_a_surfaced_question_row_becomes_one_work_item(self):
        # Build a minimal question_row by hand (the shape eb.question_row emits).
        row = {
            "kind": "same_event", "event_key": "classification:a#1|episode:" + "c" * 24,
            "telling_ref": TELLING_A, "candidate_episode_id": "episode:" + "c" * 24,
            "candidate_kind": "episode", "candidate_members": [TELLING_B],
            "relation_hint": "same", "part_of_suggestive": False, "verdict": "asked",
            "failed_conditions": ["label_stems_match"], "signals": ["place"],
            "surfaced": True, "identity_rule_version": ei.IDENTITY_RULE_VERSION,
            "score_inputs": {"plausibility": 2, "label_match": False,
                             "candidate_is_dated": True, "telling_recency": NOW,
                             "candidate_member_count": 1},
            "quotes": {"telling_quote": "the trip", "episode_quote": "the launch"},
        }
        item = eb.same_event_work_item(row, now=NOW)
        self.assertIsNotNone(item)
        self.assertEqual(item["kind"], "same_event")
        self.assertEqual(item["telling_quote"], "the trip")
        self.assertEqual(item["episode_quote"], "the launch")
        self.assertIn("“the trip”", item["prompt_intent"])

    def test_an_unsurfaced_row_mints_no_item(self):
        row = {
            "kind": "same_event", "event_key": "x|y", "telling_ref": TELLING_A,
            "candidate_episode_id": "episode:" + "c" * 24, "candidate_kind": "episode",
            "candidate_members": [], "relation_hint": "same",
            "part_of_suggestive": False, "verdict": "asked", "failed_conditions": [],
            "signals": [], "surfaced": False, "identity_rule_version": ei.IDENTITY_RULE_VERSION,
            "score_inputs": {"plausibility": 1, "label_match": False,
                             "candidate_is_dated": False, "telling_recency": NOW,
                             "candidate_member_count": 0},
            "quotes": {"telling_quote": "", "episode_quote": ""},
        }
        plan = eb.BinderPlan(questions=(row,))
        self.assertEqual(eb.same_event_work_items(plan, now=NOW), [])

    def test_an_overmerge_audit_row_becomes_one_work_item(self):
        plan = eb.BinderPlan(overmerges=(
            {"kind": "possible_overmerge", "item_id": "possible_overmerge:" + "d" * 24,
             "episode_id": "episode:" + "e" * 24, "telling_refs": [TELLING_A, TELLING_B],
             "finding": "disjoint_stated_bounds", "reason": "their stated bounds do not overlap",
             "identity_rule_version": ei.IDENTITY_RULE_VERSION},
        ))
        items = eb.possible_overmerge_work_items(plan, now=NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "possible_overmerge")

    def test_a_no_action_reaudit_mints_nothing(self):
        """§4.5's FORBIDDEN_REAUDIT_ACTIONS: a re-audit that declined to mint
        must not somehow become a work item downstream."""
        plan = eb.BinderPlan(reaudits=(
            {"action": erc.REAUDIT_NO_ACTION, "trigger": "maintenance_sweep",
             "reason": "already answered"},
        ))
        self.assertEqual(eb.possible_overmerge_work_items(plan, now=NOW), [])

    def test_a_mint_reaudit_becomes_one_work_item(self):
        plan = eb.BinderPlan(reaudits=(
            {"action": erc.REAUDIT_MINT, "kind": "possible_overmerge",
             "item_id": "possible_overmerge:" + "f" * 24,
             "pair": "episode:" + "1" * 24 + "|episode:" + "2" * 24,
             "telling_ref": TELLING_A, "existing_bind": "episode:" + "1" * 24,
             "new_candidate": "episode:" + "2" * 24,
             "identity_rule_version": ei.IDENTITY_RULE_VERSION,
             "reason": "a new plausible candidate appeared"},
        ))
        items = eb.possible_overmerge_work_items(plan, now=NOW)
        self.assertEqual(len(items), 1)


# ==========================================================================
# §2b. The per-UNIT surfacing cap (lifehug#300) still holds through generation
# ==========================================================================
#
# #300 (merged as this branch's own rebase target, v269) fixed the per-telling
# surfacing cap into a per-UNIT one: after two judged directions collapse into
# one row, a telling is `telling_ref` on only SOME of the pairs it is
# genuinely in, so `apply_caps` now counts a pair against BOTH `row["units"]`
# entries. This section proves that fix's promise survives one more hop: the
# WORK ITEMS this phase mints from `apply_caps`'s own `surfaced` flag never
# exceed one surfaced item per unit, on a real (not hand-built) plan.

_FIXTURE = json.loads(
    (ROOT / "tests" / "goldens" / "event_identity_i2_binder.json").read_text("utf-8")
)


def _revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _fixture_claim(**overrides) -> dict:
    source = overrides.pop("source")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": _revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence somebody said")}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit", "confidence": 0.9, "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def _fixture_value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def _fixture_birth_claim() -> dict:
    return _fixture_claim(
        claim_type="date", subject_mention="I", event_kind="birth",
        source="landmark:entry-birth", quote="I was born.",
        temporal_value=_fixture_value(_FIXTURE["owner_birth"]),
    )


def _fixture_telling_claim(row: dict) -> dict:
    common = {
        "subject_mention": "I", "event_kind": row["event_kind"],
        "source": row["telling_ref"], "quote": row["quote"],
        "event_mention": row["mention"], "place_mentions": list(row.get("places") or ()),
    }
    if row["kind"] == "classifier":
        common["event_ref"] = tp.derive_node_id(
            node_kind="event", event_kind=row["event_kind"],
            subject_refs=["I"], discriminator=row["telling_ref"],
        )
    if row["dated"] is None:
        return _fixture_claim(claim_type="occurrence", **common)
    return _fixture_claim(claim_type="date", temporal_value=_fixture_value(row["dated"]),
                          **common)


def _fixture_participant_claims(row: dict) -> list:
    found = []
    for name in row.get("participants") or ():
        found.append(_fixture_claim(
            claim_type="occurrence", subject_mention=name, event_kind=row["event_kind"],
            source=row["telling_ref"], quote=row["quote"], event_mention=row["mention"],
            place_mentions=list(row.get("places") or ()),
        ))
    return found


def _fixture_claims() -> list:
    found = [_fixture_birth_claim()]
    for row in _FIXTURE["tellings"]:
        found.append(_fixture_telling_claim(row))
        found.extend(_fixture_participant_claims(row))
    return found


def _fixture_plan(**kwargs) -> "eb.BinderPlan":
    kwargs.setdefault("now", "2026-08-30T12:00:00Z")
    return eb.plan(_fixture_claims(), **kwargs)


class CapConsistencyTests(unittest.TestCase):
    """§6.1's caps, read through generation, on the founder-shaped fixture."""

    @classmethod
    def setUpClass(cls):
        cls.result = _fixture_plan()
        cls.items = eb.same_event_work_items(cls.result, now="2026-08-30T12:00:00Z")

    def test_the_result_has_real_units_worth_capping(self):
        """The fixture must actually exercise more than one candidate per
        telling, or this whole class would pass for having nothing to cap."""
        per_unit: dict = {}
        for row in self.result.questions:
            for side in row["units"]:
                per_unit[side] = per_unit.get(side, 0) + 1
        self.assertGreater(max(per_unit.values(), default=0), 1)

    def test_no_unit_backs_more_than_one_surfaced_work_item(self):
        """`apply_caps` counts a pair against BOTH its units (#300); a
        generation pass that only read `telling_ref` would let a unit that
        lost the `home_key` coin toss quietly back a second surfaced item."""
        per_unit_surfaced: dict = {}
        for item in self.items:
            for side in item["event_ref"].split(erc.PAIR_KEY_SEPARATOR):
                per_unit_surfaced[side] = per_unit_surfaced.get(side, 0) + 1
        for side, count in per_unit_surfaced.items():
            with self.subTest(unit=side):
                self.assertLessEqual(count, eb.SURFACED_PAIRS_PER_TELLING)

    def test_every_surfaced_question_row_became_a_work_item(self):
        """The generation layer drops nothing `apply_caps` already surfaced —
        it only ever ADDS the cap-respecting filter of skipping the
        UNSURFACED rows."""
        surfaced_keys = {row["event_key"] for row in self.result.questions
                         if row["surfaced"]}
        item_keys = {item["event_ref"] for item in self.items}
        self.assertEqual(surfaced_keys, item_keys)


# ==========================================================================
# §3. same_event — the five answers (design §6.1)
# ==========================================================================


class SameEventAnswerTests(unittest.TestCase):
    def test_same_against_an_existing_episode_files_a_confirmed_binding(self):
        root = _vault(self, "iq-same-existing")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="same", telling_quote="B", episode_quote="A", now=NOW,
        )
        self.assertEqual(result["episode_id"], episode_id)
        binding = result["binding"]
        self.assertEqual(binding["relation"], efc.GROUPING_RELATION)
        self.assertEqual(binding["origin"], "confirmed")
        self.assertTrue(binding["relative_path"].startswith(ei.HUMAN_BINDINGS_DIR))

    def test_same_supersedes_a_state_side_proposal(self):
        """The origin-transition rule (§3.3): confirming Same over a prior
        `proposed` binding supersedes it, and the identity set carries no
        unsuperseded twin."""
        root = _vault(self, "iq-same-supersede")
        episode_id = _create_episode(root, [TELLING_A])
        proposed, _ = ei.file_event_identity(
            root, telling_ref=TELLING_B, episode_id=episode_id,
            relation=efc.GROUPING_RELATION, origin="proposed",
            rule_version=ei.IDENTITY_RULE_VERSION, created_at=NOW,
        )
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="same", now=NOW,
        )
        self.assertEqual(result["binding"]["supersedes"], proposed["identity_id"])
        active = ei.validate_identity_set(ei.load_event_identities(root))
        active_ids = {row["identity_id"] for row in active}
        self.assertNotIn(proposed["identity_id"], active_ids)
        self.assertIn(result["binding"]["identity_id"], active_ids)

    def test_same_against_a_prospective_pair_creates_a_human_episode(self):
        """R1 declined this pair (that is why it is a question); the create
        this module files is `authority: human`, a DIFFERENT id than the
        `authority: deterministic` prospective id the pair was keyed by."""
        root = _vault(self, "iq-same-prospective")
        prospective_id = eb.prospective_episode_id(sorted([TELLING_A, TELLING_B]))
        self.assertFalse(iq._episode_exists(root, prospective_id))
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_A, candidate_episode_id=prospective_id,
            candidate_telling_ref=TELLING_B, answer="same", now=NOW,
        )
        self.assertNotEqual(result["episode_id"], prospective_id)
        self.assertTrue(iq._episode_exists(root, result["episode_id"]))
        active = ei.validate_identity_set(ei.load_event_identities(root))
        tellings = {row["telling_ref"] for row in active
                    if row["episode_id"] == result["episode_id"]}
        self.assertEqual(tellings, {TELLING_A, TELLING_B})
        self.assertTrue(all(row["origin"] == "confirmed" for row in active
                            if row["episode_id"] == result["episode_id"]))

    def test_same_against_a_prospective_pair_needs_the_sibling(self):
        root = _vault(self, "iq-same-needs-sibling")
        prospective_id = eb.prospective_episode_id(sorted([TELLING_A, TELLING_B]))
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_same_event_answer(
                root, telling_ref=TELLING_A, candidate_episode_id=prospective_id,
                answer="same", now=NOW,
            )
        self.assertEqual(caught.exception.code, "identity_answer_needs_sibling")

    def test_part_of_files_a_confirmed_containment_binding(self):
        """§3.3: `part_of` is already admitted at `confirmed` origin —
        `validate_event_identity` pins only `deterministic` to `same`; no
        validator amendment was needed for this phase."""
        root = _vault(self, "iq-part-of")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="part_of", now=NOW,
        )
        self.assertEqual(result["binding"]["relation"], "part_of")
        self.assertEqual(result["binding"]["origin"], "confirmed")

    def test_related_files_a_confirmed_related_binding(self):
        root = _vault(self, "iq-related")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="related", now=NOW,
        )
        self.assertEqual(result["binding"]["relation"], "related")

    def test_different_files_a_pair_permanent_not_same_binding(self):
        root = _vault(self, "iq-different")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_C, candidate_episode_id=episode_id,
            answer="different", now=NOW,
        )
        self.assertEqual(result["binding"]["relation"], "not_same")

    def test_answering_the_same_pair_twice_is_idempotent_by_digest(self):
        """§5.8 row 2: "answering twice is idempotent by record digest" — a
        repeated HUMAN answer must not chain a fresh supersession onto
        itself."""
        root = _vault(self, "iq-idempotent")
        episode_id = _create_episode(root, [TELLING_A])
        first = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_C, candidate_episode_id=episode_id,
            answer="different", now=NOW,
        )
        second = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_C, candidate_episode_id=episode_id,
            answer="different", now=NOW,
        )
        self.assertEqual(first["binding"]["identity_id"], second["binding"]["identity_id"])
        self.assertFalse(second["created"])

    def test_not_sure_files_no_binding_only_a_deferral(self):
        root = _vault(self, "iq-not-sure")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="not_sure", now=NOW,
        )
        self.assertEqual(result["answer"], "not_sure")
        # Only the pre-existing episode binding is on disk — "not sure"
        # asserts nothing about the world (§2.2) and adds no new binding.
        self.assertEqual(len(ei.load_event_identities(root)), 1)
        self.assertTrue(iq.read_deferrals(root))

    def test_an_unknown_answer_is_refused(self):
        root = _vault(self, "iq-unknown-answer")
        episode_id = _create_episode(root, [TELLING_A])
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_same_event_answer(
                root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
                answer="maybe", now=NOW,
            )
        self.assertEqual(caught.exception.code, "identity_answer_unknown")


# ==========================================================================
# §4. "Not sure" — cooldown and reopening (§13.4, §2.2)
# ==========================================================================


class NotSureCooldownTests(unittest.TestCase):
    def test_a_deferred_pair_is_not_reasked_inside_the_cooldown(self):
        root = _vault(self, "iq-cooldown-active")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="not_sure", now=NOW,
        )
        self.assertTrue(iq.is_pair_deferred(root, result["event_key"], now=NOW))

    def test_the_cooldown_expires_after_90_days(self):
        root = _vault(self, "iq-cooldown-expires")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="not_sure", now=NOW,
        )
        self.assertEqual(erc.DEFERRAL_COOLDOWN_DAYS, 90)
        self.assertFalse(iq.is_pair_deferred(root, result["event_key"], now=LATER))

    def test_material_new_evidence_reopens_the_pair_early(self):
        """§13.4: "reopens early on material new evidence — a new date on
        either side."""
        root = _vault(self, "iq-cooldown-reopen")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="not_sure", telling_quote="q1", episode_quote="q2", now=NOW,
        )
        self.assertFalse(
            iq.is_pair_deferred(
                root, result["event_key"],
                evidence_signature={"telling_quote": "a NEW date appeared", "episode_quote": "q2"},
                now=NOW,
            )
        )

    def test_unchanged_evidence_does_not_reopen_it(self):
        root = _vault(self, "iq-cooldown-unchanged")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="not_sure", telling_quote="q1", episode_quote="q2", now=NOW,
        )
        self.assertTrue(
            iq.is_pair_deferred(
                root, result["event_key"],
                evidence_signature={"telling_quote": "q1", "episode_quote": "q2"},
                now=NOW,
            )
        )

    def test_a_pair_with_no_deferral_is_never_reported_deferred(self):
        root = _vault(self, "iq-cooldown-absent")
        self.assertFalse(iq.is_pair_deferred(root, "nothing|here", now=NOW))


# ==========================================================================
# §5. possible_overmerge — the four answers (§6.3, §12.5)
# ==========================================================================


class PossibleOvermergeAnswerTests(unittest.TestCase):
    def test_keep_together_writes_nothing(self):
        """§5.6/FORBIDDEN_REAUDIT_ACTIONS: a system CONFIRM is refused; a
        person confirming the bind is simply not an identity write."""
        root = _vault(self, "iq-keep-together")
        episode_id = _create_episode(root, [TELLING_A])
        before = ei.load_event_identities(root)
        result = iq.resolve_possible_overmerge_answer(
            root, telling_ref=TELLING_A, episode_id=episode_id, answer="keep_together",
        )
        self.assertFalse(result["written"])
        self.assertEqual(ei.load_event_identities(root), before)

    def test_fix_the_date_writes_nothing_and_names_the_next_step(self):
        root = _vault(self, "iq-fix-the-date")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_possible_overmerge_answer(
            root, telling_ref=TELLING_A, episode_id=episode_id, answer="fix_the_date",
        )
        self.assertFalse(result["written"])
        self.assertIn("date correction", result["next"])

    def test_part_of_supersedes_the_same_binding(self):
        root = _vault(self, "iq-overmerge-part-of")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_possible_overmerge_answer(
            root, telling_ref=TELLING_A, episode_id=episode_id, answer="part_of",
        )
        self.assertEqual(result["binding"]["relation"], "part_of")
        active = ei.validate_identity_set(ei.load_event_identities(root))
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["relation"], "part_of")

    def test_split_dispatches_to_split_episode(self):
        root = _vault(self, "iq-overmerge-split")
        episode_id = _create_episode(root, [TELLING_A, TELLING_B])
        new_episode_id = "episode:" + "9" * 24
        result = iq.resolve_possible_overmerge_answer(
            root, telling_ref=TELLING_A, episode_id=episode_id, answer="split",
            destinations={TELLING_B: new_episode_id},
        )
        self.assertIn("routing", result)
        self.assertIn("envelope", result)

    def test_split_without_destinations_is_refused(self):
        root = _vault(self, "iq-overmerge-split-refused")
        episode_id = _create_episode(root, [TELLING_A])
        with self.assertRaises(iq.IdentityQuestionsError):
            iq.resolve_possible_overmerge_answer(
                root, telling_ref=TELLING_A, episode_id=episode_id, answer="split",
            )

    def test_an_unknown_overmerge_answer_is_refused(self):
        root = _vault(self, "iq-overmerge-unknown")
        episode_id = _create_episode(root, [TELLING_A])
        with self.assertRaises(iq.IdentityQuestionsError) as caught:
            iq.resolve_possible_overmerge_answer(
                root, telling_ref=TELLING_A, episode_id=episode_id, answer="destroy",
            )
        self.assertEqual(caught.exception.code, "identity_overmerge_answer_unknown")


# ==========================================================================
# §6. The split gesture — §5.5's rows, end to end
# ==========================================================================


class SplitEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.root = _vault(self, "iq-split")
        self.episode_id = _create_episode(self.root, [TELLING_A, TELLING_B, TELLING_C])
        self.new_episode_id = "episode:" + "b" * 24

    def test_the_survivor_keeps_its_id_and_departures_get_none(self):
        result = iq.split_episode(
            self.root, episode_id=self.episode_id,
            destinations={TELLING_C: erc.SPLIT_DESTINATION_STANDALONE,
                          TELLING_B: self.new_episode_id},
        )
        active = ei.validate_identity_set(ei.load_event_identities(self.root))
        by_pair = {(row["telling_ref"], row["episode_id"]): row["relation"] for row in active}
        self.assertEqual(by_pair[(TELLING_A, self.episode_id)], efc.GROUPING_RELATION)
        self.assertEqual(by_pair[(TELLING_B, self.new_episode_id)], efc.GROUPING_RELATION)
        self.assertEqual(by_pair[(TELLING_C, self.episode_id)], ei.SPLIT_DEPARTURE_RELATION)
        self.assertEqual(by_pair[(TELLING_B, self.episode_id)], ei.SPLIT_DEPARTURE_RELATION)

    def test_replay_is_a_no_op(self):
        destinations = {TELLING_C: erc.SPLIT_DESTINATION_STANDALONE,
                        TELLING_B: self.new_episode_id}
        iq.split_episode(self.root, episode_id=self.episode_id, destinations=destinations)
        again = iq.split_episode(self.root, episode_id=self.episode_id, destinations=destinations)
        self.assertFalse(again["envelope"]["created"])

    def test_every_reference_kind_routes_somewhere_and_unattributable_ones_become_mirror_judgments(self):
        references = [
            {"reference_kind": "ordering_constraint", "reference_id": "oc1",
             "candidates": [TELLING_C, TELLING_B]},
            {"reference_kind": "era_membership", "reference_id": "em1",
             "candidates": [TELLING_C]},
            {"reference_kind": "display_decision", "reference_id": "dd1",
             "candidates": [TELLING_B]},
            {"reference_kind": "episode_label", "reference_id": "el1", "candidates": []},
            {"reference_kind": "work_item", "reference_id": "wi1", "candidates": []},
            {"reference_kind": "open_session", "reference_id": "os1", "candidates": []},
            {"reference_kind": "other_decision", "reference_id": "od1", "candidates": []},
        ]
        result = iq.split_episode(
            self.root, episode_id=self.episode_id,
            destinations={TELLING_C: erc.SPLIT_DESTINATION_STANDALONE,
                          TELLING_B: self.new_episode_id},
            references=references,
        )
        routing = result["routing"]
        routed_ids = {row["reference_id"] for row in routing["routes"]}
        judged_ids = {row["reference_id"] for row in routing["mirror_judgments"]}
        self.assertEqual(routed_ids | judged_ids, {row["reference_id"] for row in references})
        # The genuinely ambiguous "other_decision" row is ALWAYS a Mirror
        # judgment (§5.5's catch-all rule) — never silently routed.
        self.assertIn("od1", judged_ids)


# ==========================================================================
# §7. Never-ask-again proofs (§13.3, §13.4)
# ==========================================================================


class NeverAskAgainTests(unittest.TestCase):
    def test_different_is_never_reproposed_or_reasked(self):
        """§13.3 (already proven at the binder level by #299) — the
        WORK-ITEM side: `reaudit` consults `answered_pairs` and refuses to
        mint for a pair the person already answered Different."""
        episode_a = "episode:" + "1" * 24
        episode_b = "episode:" + "2" * 24
        pair_key = erc.pair_event_key(TELLING_A, episode_b)
        outcome = erc.reaudit(
            trigger="maintenance_sweep", telling_ref=TELLING_A,
            bound_episode_id=episode_a, candidate_episode_id=episode_b,
            answered_pairs=({"telling_ref": TELLING_A, "candidate_episode_id": episode_b},),
        )
        self.assertEqual(outcome["action"], erc.REAUDIT_NO_ACTION)
        self.assertEqual(outcome["pair"], pair_key)

    def test_a_not_same_binding_also_blocks_the_reaudit(self):
        episode_a = "episode:" + "1" * 24
        episode_b = "episode:" + "2" * 24
        bindings = [{
            "telling_ref": TELLING_A, "episode_id": episode_b, "relation": "not_same",
            "origin": "confirmed", "status": "active",
        }]
        outcome = erc.reaudit(
            trigger="maintenance_sweep", telling_ref=TELLING_A,
            bound_episode_id=episode_a, candidate_episode_id=episode_b,
            bindings=bindings,
        )
        self.assertEqual(outcome["action"], erc.REAUDIT_NO_ACTION)

    def test_not_sure_is_not_reasked_inside_the_cooldown_work_item_side(self):
        root = _vault(self, "iq-never-ask-not-sure")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="not_sure", now=NOW,
        )
        # A generation pass consulting deferrals must skip this pair.
        self.assertTrue(iq.is_pair_deferred(root, result["event_key"], now=NOW))
        self.assertFalse(iq.is_pair_deferred(root, result["event_key"], now=LATER))

    def test_a_telling_bound_same_into_a_dated_episode_is_never_asked_missing_anchor(self):
        """§13.3: structurally proven at I1 (a `same`-bound telling's claims
        group under the episode's node, so `missing_anchor` is per-node, not
        per-telling) — this is the work-item-generation-side test the task
        asks for: a same_event answer never itself mints a missing_anchor
        row for the telling it just bound."""
        root = _vault(self, "iq-never-missing-anchor")
        episode_id = _create_episode(root, [TELLING_A])
        result = iq.resolve_same_event_answer(
            root, telling_ref=TELLING_B, candidate_episode_id=episode_id,
            answer="same", now=NOW,
        )
        self.assertEqual(result["binding"]["relation"], efc.GROUPING_RELATION)
        # The confirmed `same` binding is the ONLY record this answer filed —
        # no missing_anchor (or any other) work item rides along it.
        operations = ei.load_episode_operations(root)
        self.assertEqual(len(operations), 1)  # the original deterministic create
        self.assertEqual(operations[0]["op"], "create")


# ==========================================================================
# §8. The listener leaf (§6.4, ADR 0029 amendment)
# ==========================================================================


class ListenerLeafTests(unittest.TestCase):
    CANDIDATES = [
        {"ref": TELLING_A, "kind": "telling", "labels": ["the big Etherfuse event"]},
        {"ref": "episode:" + "c" * 24, "kind": "episode", "labels": ["the launch"]},
    ]

    def test_a_uniquely_resolved_assertion_is_heard(self):
        raw = json.dumps({
            "identity_assertions": [
                {"telling_hint": "the big etherfuse event",
                 "episode_hint": "the launch", "relation": "same"},
            ]
        })
        heard = gl.parse_listener_output(raw, identity_candidates=self.CANDIDATES)
        self.assertEqual(len(heard.identity_assertions), 1)
        draft = heard.identity_assertions[0]
        self.assertEqual(draft["telling_ref"], TELLING_A)
        self.assertEqual(draft["episode_id"], "episode:" + "c" * 24)
        self.assertEqual(draft["relation"], "same")
        self.assertEqual(heard.findings, ())

    def test_zero_matches_is_a_typed_refusal_not_a_binding(self):
        raw = json.dumps({
            "identity_assertions": [
                {"telling_hint": "something nobody mentioned",
                 "episode_hint": "the launch", "relation": "same"},
            ]
        })
        heard = gl.parse_listener_output(raw, identity_candidates=self.CANDIDATES)
        self.assertEqual(heard.identity_assertions, ())
        self.assertTrue(any(f.startswith(gl.IDENTITY_ASSERTION_REFUSED_PREFIX)
                            for f in heard.findings))

    def test_two_matches_is_a_typed_refusal_not_a_binding(self):
        candidates = self.CANDIDATES + [
            {"ref": TELLING_B, "kind": "telling", "labels": ["the big Etherfuse event"]},
        ]
        raw = json.dumps({
            "identity_assertions": [
                {"telling_hint": "the big etherfuse event",
                 "episode_hint": "the launch", "relation": "same"},
            ]
        })
        heard = gl.parse_listener_output(raw, identity_candidates=candidates)
        self.assertEqual(heard.identity_assertions, ())
        self.assertIn(
            gl.identity_assertion_refused(gl.IDENTITY_ASSERTION_AMBIGUOUS_TELLING),
            heard.findings,
        )

    def test_an_unknown_relation_is_refused(self):
        raw = json.dumps({
            "identity_assertions": [
                {"telling_hint": "the big etherfuse event",
                 "episode_hint": "the launch", "relation": "unknown"},
            ]
        })
        heard = gl.parse_listener_output(raw, identity_candidates=self.CANDIDATES)
        self.assertEqual(heard.identity_assertions, ())
        self.assertIn(
            gl.identity_assertion_refused(gl.IDENTITY_ASSERTION_UNKNOWN_RELATION),
            heard.findings,
        )

    def test_an_unknown_key_is_refused(self):
        raw = json.dumps({"identity_assertions": [{"telling_hint": "x", "episode_ref": "y"}]})
        heard = gl.parse_listener_output(raw, identity_candidates=self.CANDIDATES)
        self.assertEqual(heard.identity_assertions, ())
        self.assertIn(
            gl.identity_assertion_refused(gl.IDENTITY_ASSERTION_UNKNOWN_KEY),
            heard.findings,
        )

    def test_identity_assertions_is_the_fourth_and_last_heard_field(self):
        """v229's `claims` precedent, extended: a positional caller keeps
        building the same `Heard`."""
        fields = [f.name for f in gl.Heard.__dataclass_fields__.values()]
        self.assertEqual(fields[-1], "identity_assertions")
        self.assertEqual(fields, ["landmarks", "people", "findings", "claims",
                                  "identity_assertions"])

    def test_len_counts_identity_assertions_too(self):
        heard = gl.Heard(identity_assertions=({"telling_ref": TELLING_A,
                                               "episode_id": "episode:" + "c" * 24,
                                               "relation": "same"},))
        self.assertEqual(len(heard), 1)

    def test_an_ambiguous_refusal_clears_the_backstop(self):
        """Structural, like `DROPPED_NON_FAMILY` — retrying would not
        disambiguate a candidate set that genuinely has zero or two
        matches."""
        message = "the big Etherfuse event happened in 1999"
        verdict = gl.may_contain_datable(message)
        self.assertTrue(verdict.fired)  # the fixture must actually exercise the check
        finding = gl.listener_heard_nothing(
            message, [], [], claims=(), identity_assertions=(),
            findings=(gl.identity_assertion_refused(gl.IDENTITY_ASSERTION_AMBIGUOUS_TELLING),),
            verdict=verdict,
        )
        self.assertIsNone(finding)

    def test_a_resolved_identity_assertion_is_a_thing_heard(self):
        message = "the big Etherfuse event was the same as the launch"
        verdict = gl.may_contain_datable(message)
        draft = {"telling_ref": TELLING_A, "episode_id": "episode:" + "c" * 24,
                 "relation": "same"}
        finding = gl.listener_heard_nothing(
            message, [], [], claims=(), identity_assertions=(draft,),
            findings=(), verdict=verdict,
        )
        self.assertIsNone(finding)

    def test_bind_identity_assertions_adds_only_the_filers_own_fields(self):
        draft = {"telling_ref": TELLING_A, "episode_id": "episode:" + "c" * 24,
                 "relation": "same", "evidence": {}}
        bound = gl.bind_identity_assertions([draft], source_ref="conv:x", now=NOW)
        self.assertEqual(len(bound), 1)
        row = bound[0]
        self.assertEqual(row["origin"], "stated")
        self.assertEqual(row["rule_version"], ei.IDENTITY_RULE_VERSION)
        self.assertEqual(row["source_ref"], "conv:x")
        self.assertEqual(row["created_at"], NOW)
        # Every draft field survives untouched.
        for key in ("telling_ref", "episode_id", "relation", "evidence"):
            self.assertEqual(row[key], draft[key])

    def test_a_bound_stated_assertion_files_through_event_identity(self):
        root = _vault(self, "iq-listener-file")
        episode_id = _create_episode(root, [TELLING_A])
        draft = {"telling_ref": TELLING_B, "episode_id": episode_id, "relation": "related",
                 "evidence": {}}
        bound = gl.bind_identity_assertions([draft], source_ref="conv:y", now=NOW)
        record, created = ei.file_event_identity(root, **bound[0])
        self.assertTrue(created)
        self.assertEqual(record["origin"], "stated")
        self.assertEqual(record["relation"], "related")

    def test_the_prompt_carries_the_new_substitutions(self):
        prompt = gl.build_listener_prompt(
            answer="anything", identity_candidates=self.CANDIDATES,
        )
        self.assertNotIn("{identity_relations}", prompt)
        self.assertNotIn("{identity_candidates}", prompt)
        self.assertIn("same", prompt)


# ==========================================================================
# §9. The hosts: two new verbs, classified like their sibling `bind-episodes`
# ==========================================================================


class HostTests(unittest.TestCase):
    def test_resolve_work_item_is_registered_and_classified(self):
        import lifehug

        self.assertIn("resolve-work-item", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertTrue(hasattr(lifehug, "cmd_resolve_work_item"))
        parser = lifehug.build_parser()
        args = parser.parse_args([
            "resolve-work-item", "--kind", "same_event",
            "--telling-ref", TELLING_A, "--episode-id", "episode:" + "a" * 24,
            "--answer", "different",
        ])
        self.assertIs(args.func, lifehug.cmd_resolve_work_item)
        self.assertEqual(args.kind, "same_event")
        self.assertEqual(args.answer, "different")

    def test_split_episode_is_registered_and_classified(self):
        import lifehug

        self.assertIn("split-episode", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertTrue(hasattr(lifehug, "cmd_split_episode"))
        parser = lifehug.build_parser()
        args = parser.parse_args([
            "split-episode", "--episode-id", "episode:" + "a" * 24,
            "--destination", f"{TELLING_A}=standalone",
        ])
        self.assertIs(args.func, lifehug.cmd_split_episode)
        self.assertEqual(args.destination, [f"{TELLING_A}=standalone"])

    def test_split_episode_requires_at_least_one_destination(self):
        import lifehug

        with self.assertRaises(SystemExit):
            lifehug.build_parser().parse_args(
                ["split-episode", "--episode-id", "episode:" + "a" * 24]
            )

    def test_identity_questions_never_runs_inside_compile(self):
        """§4 (I2's own promise, carried forward): the writers I3 adds are
        no more inside `compile` than the binder itself is."""
        for name in ("compose.py", "temporal_publication.py", "temporal_timeline.py",
                     "temporal_projection.py", "episode_fold.py",
                     "episode_fold_contract.py", "landmark_projection.py"):
            source = (ROOT / "system" / name).read_text("utf-8")
            self.assertNotIn("identity_questions", source, f"{name} reaches identity_questions")

    def test_the_new_module_is_a_framework_file(self):
        version = json.loads((ROOT / "system" / "version.json").read_text("utf-8"))
        self.assertIn("system/identity_questions.py", version["framework_files"])
        self.assertIn("tests/test_event_identity_i3_questions.py", version["framework_files"])


if __name__ == "__main__":
    unittest.main()
