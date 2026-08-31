"""Event identity I2 — the binder.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 —
§4.1 (retrieval and the plausibility filter), §4.2 (rung R1's seven
conditions), §4.5 (the safeguards that ship with R1), §5.6 (the re-audit),
§6.1's caps, §8's dry run, and the §13.3 promises. The pure decisions this
phase stands on were settled in I0 and are CALLED, never re-implemented.

**The fixture is the founder's own shape** (`tests/goldens/
event_identity_i2_binder.json`), carried forward from I1's and given the two
things a binder needs that a fold did not: tellings nobody has decided yet,
and a second story so a run has something to be wrong about. Every name,
date, place and word is synthetic; NOTHING here reads ~/Workspace/dave.

Every negative below was run against a build with its guard removed and SEEN
failing first; the evidence table is in the PR body.
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

import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "goldens" / "event_identity_i2_binder.json").read_text("utf-8")
)
EXPECTED = FIXTURE["expected"]
NOW = "2026-08-30T12:00:00Z"


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


def _value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def birth_claim() -> dict:
    """The owner's birthday, filed the way the founder's vault actually files it.

    ``subject_mention: "birth"`` and NO ``subject_ref`` — subjects resolve
    inside the fold (v221), and this is the spelling the fold resolves to the
    owner. The fixture used to say ``"I"``, which the fold does NOT resolve to
    the owner; that went unnoticed only because the binder had its own
    owner-birth predicate, and the predicate accepted a shape the fold would
    have refused. One definition means the fixture has to be right too.
    """
    day = FIXTURE["owner_birth"]
    return _claim(claim_type="date", subject_mention="birth", event_kind="birth",
                  source="landmark:entry-birth", quote="I was born on 11 July 1981.",
                  temporal_value=_value(day))


def telling_claim(row: dict) -> dict:
    """One telling's single claim, keyed so its telling ref IS its source id.

    C1's `telling_ref_for_claim` reads the receipt's declaration first and the
    claim's own ``source_ref.source_id`` second, and for both live extractors
    the source id already IS the telling. A fixture that invented a third mint
    would be testing a shape nothing files.
    """
    common = {
        "subject_mention": "I",
        "event_kind": row["event_kind"],
        "source": row["telling_ref"],
        "quote": row["quote"],
        "event_mention": row["mention"],
        "place_mentions": list(row.get("places") or ()),
    }
    if row["kind"] == "classifier":
        common["event_ref"] = tp.derive_node_id(
            node_kind="event", event_kind=row["event_kind"],
            subject_refs=["I"], discriminator=row["telling_ref"],
        )
    if row["dated"] is None:
        return _claim(claim_type="occurrence", **common)
    return _claim(claim_type="date", temporal_value=_value(row["dated"]), **common)


def tellings(*roles: str) -> list:
    rows = FIXTURE["tellings"]
    if not roles:
        return list(rows)
    return [row for row in rows if row["role"] in roles]


def refs(*roles: str) -> list:
    return [row["telling_ref"] for row in tellings(*roles)]


def ref(role: str) -> str:
    return refs(role)[0]


def participant_claims(row: dict) -> list:
    """The other people one telling names, as their own claims.

    A telling cites 1..n claims (§2.1), and a classifier that hears "with AJ"
    files AJ's own occurrence beside the owner's. Without it AJ is only a word
    in a label — which is exactly the difference between the CAST agreeing
    (§4.2 condition 4) and the LABEL agreeing (condition 3).
    """
    found = []
    for name in row.get("participants") or ():
        found.append(_claim(
            claim_type="occurrence", subject_mention=name,
            event_kind=row["event_kind"], source=row["telling_ref"],
            quote=row["quote"], event_mention=row["mention"],
            place_mentions=list(row.get("places") or ()),
        ))
    return found


def claims_for(*roles: str) -> list:
    found = [birth_claim()]
    for row in tellings(*roles):
        found.append(telling_claim(row))
        found.extend(participant_claims(row))
    return found


def frames():
    """The age frames THE FOLD calculates for this fixture — never a private
    copy of the arithmetic (the live `age_frames: 0` defect)."""
    return eb.fold_age_frames(claims_for())


def as_input(records: object) -> object:
    """Only the three keys `episode_fold` admits.

    The record builders below hand back the ids they minted too, because a
    test that had to re-derive an episode id to assert on it would be
    re-implementing the thing under test.
    """
    if not isinstance(records, dict):
        return records
    return {key: records[key] for key in ef.IDENTITY_INPUT_KEYS if key in records}


def run(*roles: str, episode_records=(), **kwargs) -> eb.BinderPlan:
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("frames", frames())
    return eb.plan(claims_for(*roles), episode_records=as_input(episode_records), **kwargs)


def records_of(result: eb.BinderPlan) -> dict:
    """A plan's envelopes and proposals as an `episode_records` input.

    The same shape `episode_fold.load_episode_records` returns, so a two-stage
    run — bind, then look again — reads exactly what a vault would hand it.
    """
    operations, bindings = [], []
    for row in result.envelopes:
        operations.append(row["operation"])
        bindings.extend(row["bindings"])
    bindings.extend(result.proposals)
    return {"operations": operations, "bindings": bindings}


def direction_of(result: eb.BinderPlan, telling_ref: str, candidate_key: str) -> eb.Pair:
    """ONE judged direction — for the four asymmetric conditions.

    R1 judges both ways; `result.pairs` keeps one row per unordered pair. A
    test about repeatable protection, episode maturity, or a stem that matches
    one way round has to name the direction it means.
    """
    for row in result.directional:
        if row.telling_ref == telling_ref and row.candidate_key == candidate_key:
            return row
    raise AssertionError(f"no judged direction {telling_ref} vs {candidate_key}")


def pair_of(result: eb.BinderPlan, telling_ref: str, candidate_key: str) -> eb.Pair:
    """The ONE collapsed row for this pair, whichever way round it is named."""
    wanted = tuple(sorted((telling_ref, candidate_key)))
    for row in result.pairs:
        if row.units == wanted:
            return row
        if (row.telling_ref, row.candidate_key) == (telling_ref, candidate_key):
            return row
    raise AssertionError(f"no pair {telling_ref} vs {candidate_key}")


def verdict(result: eb.BinderPlan, telling_ref: str, candidate_key: str) -> str:
    try:
        return pair_of(result, telling_ref, candidate_key).verdict
    except AssertionError:
        return ""


ETHERFUSE = ("etherfuse_anchor", "etherfuse_same")
RIDGELINE = ("ridgeline",)


# ==========================================================================
# §4.2 condition 3 — the stems, and the fixed verb table
# ==========================================================================


class LabelStemTests(unittest.TestCase):
    def test_the_founders_two_sentences_reduce_to_one_stem(self):
        """§4.2's own worked example, byte for byte: `etherfuse-found`."""
        self.assertEqual(eb.label_stem("Started Etherfuse"), EXPECTED["etherfuse_stem"])
        self.assertEqual(
            eb.label_stem("Co-founded Etherfuse with AJ", ["AJ"]),
            EXPECTED["etherfuse_stem"],
        )
        self.assertEqual(eb.label_stem("Joined Ridgeline"), EXPECTED["ridgeline_stem"])

    def test_the_idea_is_a_different_stem(self):
        self.assertNotEqual(eb.label_stem("The idea for Etherfuse"),
                            EXPECTED["etherfuse_stem"])

    def test_a_participant_is_never_also_a_label_token(self):
        """Condition 4 counts the cast; counting it in the label too would let
        ONE fact satisfy two supposedly independent signals."""
        self.assertNotIn("aj", eb.label_stem("Co-founded Etherfuse with AJ", ["AJ"]))
        self.assertIn("aj", eb.label_stem("Co-founded Etherfuse with AJ"))

    def test_an_unknown_verb_stays_a_subject_token(self):
        """So an unrecognized verb can only ever make a stem MORE specific,
        which can only ever refuse a bind."""
        self.assertEqual(eb.label_stem("Etherfuse ran with three people"),
                         "etherfuse-people-ran")

    def test_the_verb_table_is_a_table_and_not_a_stemmer(self):
        self.assertEqual(eb.EVENT_VERB_STEMS["cofounded"], "found")
        self.assertEqual(eb.EVENT_VERB_STEMS["started"], "found")
        self.assertNotIn("ran", eb.EVENT_VERB_STEMS)
        self.assertNotIn("sold", eb.EVENT_VERB_STEMS.get("bought", ""))
        self.assertEqual(len(set(eb.EVENT_VERB_STEMS.values())), 18)
        self.assertGreaterEqual(len(eb.EVENT_VERB_STEMS), 20)

    def test_a_label_with_nothing_left_never_matches(self):
        self.assertEqual(eb.label_stem("the and of"), "")
        self.assertEqual(eb.label_stem(""), "")


class KindFamilyTests(unittest.TestCase):
    def test_moment_is_a_wildcard_and_not_a_solvent(self):
        self.assertTrue(eb.kinds_compatible("moment", "job"))
        self.assertTrue(eb.kinds_compatible("moment", "school"))
        self.assertFalse(eb.kinds_compatible("job", "school"))

    def test_a_kind_in_no_family_is_compatible_with_nothing(self):
        """§13.3: `the idea for Etherfuse` is refused by the KIND-FAMILY gate."""
        self.assertEqual(eb.kind_families("idea"), frozenset())
        self.assertFalse(eb.kinds_compatible("idea", "job"))
        self.assertFalse(eb.kinds_compatible("idea", "moment"))

    def test_every_seeded_event_kind_has_a_family(self):
        """PARITY: a kind added to `temporal_claims.EVENT_KINDS` upstream must
        not silently fall out of every family and become un-bindable."""
        missing = sorted(kind for kind in tc.EVENT_KINDS if not eb.kind_families(kind))
        self.assertEqual(missing, [], f"seeded event kinds with no family: {missing}")

    def test_repeatable_is_identity_resolutions_list_and_not_a_copy(self):
        import identity_resolution as ir

        for kind in ir.REPEATABLE_EVENT_KINDS:
            self.assertTrue(eb.is_repeatable(kind))
        self.assertFalse(eb.is_repeatable("moment"))


# ==========================================================================
# §4.1 — retrieval and the plausibility filter
# ==========================================================================


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.views = eb.telling_views(claims_for())
        self.units = eb.candidates(self.views)

    def test_the_seven_signals_are_the_designs_six_plus_i2bs_entity(self):
        """§4.1's six, and amendment v4.2 §12b ruling 1's seventh.

        `entity` sits beside `participant` because that is what it is a
        widening of: the roster's recognition of a name the participant set
        never carried."""
        self.assertEqual(eb.RETRIEVAL_SIGNALS,
                         ("participant", "entity", "place", "era",
                          "bounds_in_frame", "label_token", "source_document"))

    def test_the_score_is_one_point_per_signal_and_nothing_else(self):
        signals = eb.retrieval_signals(
            self.views[ref("etherfuse_anchor")],
            self.units[ref("etherfuse_same")], frames=frames(),
        )
        self.assertEqual(eb.plausibility(signals), len(signals))
        self.assertIn("place", signals)
        self.assertIn("label_token", signals)
        self.assertIn("bounds_in_frame", signals)

    def test_two_stories_in_two_age_frames_never_retrieve_each_other(self):
        signals = eb.retrieval_signals(
            self.views[ref("etherfuse_anchor")],
            self.units[ref("ridgeline")], frames=frames(),
        )
        self.assertEqual(signals, ())

    def test_a_candidate_below_the_floor_is_dropped_silently(self):
        """§4.1: absence is not a decision. Dropped candidates produce no
        record, no question and no negative — only a count."""
        found = eb.retrieve(self.views[ref("etherfuse_anchor")], self.units,
                            frames=frames())
        for candidate, signals in found:
            self.assertGreaterEqual(eb.plausibility(signals), eb.PLAUSIBILITY_FLOOR)
            self.assertNotEqual(candidate.key, ref("ridgeline"))
        result = run()
        self.assertGreater(result.counts["dropped_below_floor"], 0)
        for row in result.questions:
            self.assertGreaterEqual(row["score_inputs"]["plausibility"],
                                    eb.PLAUSIBILITY_FLOOR)

    def test_the_era_signal_fires_when_a_host_supplies_memberships(self):
        """§4.1's era signal is an INPUT, not a derivation — era membership is
        the fold's answer, keyed on a calculated node id, and re-deriving it
        here would be a second copy of the eras fold inside the binder. A host
        that holds it passes it; without it a pair scores one signal fewer,
        which can only ever retrieve LESS."""
        era = "era:" + "c" * 24
        pair = (ref("etherfuse_asked"), ref("etherfuse_anchor"))
        views = eb.telling_views(claims_for())
        units = eb.candidates(views)
        bare = eb.retrieval_signals(views[pair[0]], units[pair[1]], frames=frames())
        self.assertNotIn("era", bare)
        views = eb.telling_views(claims_for(),
                                 era_memberships={pair[0]: [era], pair[1]: [era]})
        units = eb.candidates(views)
        with_era = eb.retrieval_signals(views[pair[0]], units[pair[1]], frames=frames())
        self.assertIn("era", with_era)
        self.assertEqual(eb.plausibility(with_era), eb.plausibility(bare) + 1)
        self.assertTrue(eb.ERA_SIGNAL_IS_SUPPLIED_BY_THE_HOST)

    def test_a_shared_era_alone_never_binds_anything(self):
        """It is a RETRIEVAL signal and not one of condition 4's four: living
        through the same stretch of life is not evidence that two accounts are
        about one event."""
        era = "era:" + "c" * 24
        memberships = {row["telling_ref"]: [era] for row in tellings()}
        result = run(era_memberships=memberships)
        self.assertEqual([row["operation"]["members"] for row in result.envelopes],
                         [EXPECTED["etherfuse_bind_members"]])
        for pair in result.pairs:
            self.assertNotIn("era", eb.independent_signals(
                result.views[pair.telling_ref],
                eb.candidates(result.views,
                              episode_records=())[pair.candidate_key]))

    def test_bounds_in_frame_cannot_fire_without_frames(self):
        """Age frames have ONE definition (`cross_dating.age_frames`); with
        none supplied the signal is absent rather than approximated."""
        signals = eb.retrieval_signals(
            self.views[ref("etherfuse_anchor")], self.units[ref("etherfuse_same")],
            frames=(),
        )
        self.assertNotIn("bounds_in_frame", signals)

    def test_a_telling_about_an_era_is_never_a_unit(self):
        """§5.1's first case: a telling about the era ITSELF is not groupable."""
        era_claim = _claim(
            claim_type="date", subject_mention="era:" + "a" * 24, event_kind="span",
            source="landmark:entry-college", quote="College ran 1999 to 2003.",
            event_mention="College", temporal_value=_value("1999"),
        )
        views = eb.telling_views([era_claim])
        self.assertFalse(views["landmark:entry-college"].eligible)
        self.assertEqual(views["landmark:entry-college"].ineligible_reason,
                         ei.INELIGIBLE_TELLING_IS_AN_ERA)
        self.assertEqual(eb.candidates(views), {})

    def test_a_telling_whose_every_claim_is_era_bound_is_never_a_unit(self):
        """C3 refuses each era-bound claim individually, so a bind on a telling
        made only of them would group nothing and be reported."""
        era_claim = _claim(
            claim_type="date", subject_mention="I", event_kind="span",
            source="landmark:entry-mission", quote="The Mission ran two years.",
            event_ref="era:" + "b" * 24, event_mention="the Mission",
            temporal_value=_value("2001"),
        )
        views = eb.telling_views([era_claim])
        self.assertFalse(views["landmark:entry-mission"].eligible)
        self.assertEqual(views["landmark:entry-mission"].ineligible_reason,
                         efc.DIAGNOSTIC_BINDING_TO_ERA_CLAIM)

    def test_one_era_bound_claim_among_several_keeps_full_eligibility(self):
        """Audit F-pin 1's own failure case: an event that happened WITHIN an
        era is still a binding target."""
        source = "classification:mixed-story#aaaaaaaaaaaa"
        inside = _claim(
            claim_type="date", subject_mention="I", event_kind="moment",
            source=source, quote="We shipped it that spring.",
            event_mention="Shipped the first build", temporal_value=_value("2002"),
        )
        era_bound = _claim(
            claim_type="occurrence", subject_mention="I", event_kind="moment",
            source=source, quote="It was during the Mission.",
            event_ref="era:" + "b" * 24, event_mention="Shipped the first build",
        )
        views = eb.telling_views([inside, era_bound])
        self.assertTrue(views[source].eligible)


# --------------------------------------------------------------------------
# Records, built by hand where a test needs a state the binder cannot reach
# --------------------------------------------------------------------------


def create_records(members, *, kind: str = "job") -> dict:
    """One `create` envelope over these tellings — the binder's own shape."""
    operation_id = ei.operation_digest(
        authority="deterministic", op="create", rule_version=eb.RULE_VERSION,
        member_refs=list(members),
    )
    episode_id = ei.episode_id_for(operation_id)
    bindings = [
        ei.validate_event_identity({
            "telling_ref": row, "episode_id": episode_id, "relation": "same",
            "origin": "deterministic", "rule_id": eb.RULE_ID,
            "operation_id": operation_id, "created_at": NOW,
        })
        for row in sorted(members)
    ]
    operation = ei.validate_episode_operation({
        "authority": "deterministic", "op": "create", "episode_id": episode_id,
        "members": sorted(members),
        "creates_binding_ids": [row["identity_id"] for row in bindings],
        "canonical_event_kind": kind, "created_at": NOW,
    })
    return {"operations": [operation], "bindings": list(bindings),
            "episode_id": episode_id, "operation_id": operation_id}


def human_binding(telling_ref: str, episode_id: str, relation: str) -> dict:
    return ei.validate_event_identity({
        "telling_ref": telling_ref, "episode_id": episode_id, "relation": relation,
        "origin": "confirmed", "source_ref": "sources/conversations/msg-identity.md",
        "created_at": NOW,
    })


def merge_records(first: dict, second: dict) -> dict:
    """`first` absorbs `second`: every membership moved in ONE receipt."""
    survivor, absorbed = first["episode_id"], second["episode_id"]
    moved = [
        ei.validate_event_identity({
            "telling_ref": row["telling_ref"], "episode_id": survivor,
            "relation": "same", "origin": "confirmed",
            "source_ref": "sources/conversations/msg-merge.md",
            "supersedes": row["identity_id"], "created_at": NOW,
        })
        for row in second["bindings"]
    ]
    operation = ei.validate_episode_operation({
        "authority": "human", "op": "merge", "episode_id": survivor,
        "absorbed_episode_id": absorbed,
        "members": sorted(row["telling_ref"] for row in moved),
        "creates_binding_ids": [row["identity_id"] for row in moved],
        "supersedes_binding_ids": [row["identity_id"] for row in second["bindings"]],
        "aliases_created": [absorbed], "canonical_event_kind": "job",
        "created_at": NOW,
    })
    return {
        "operations": first["operations"] + second["operations"] + [operation],
        "bindings": first["bindings"] + second["bindings"] + moved,
        "episode_id": survivor, "absorbed": absorbed,
        "merge_operation_id": operation["operation_id"],
    }


# ==========================================================================
# §4.2 — R1, condition by condition (§13.3)
# ==========================================================================


class R1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.stage1 = run(*ETHERFUSE)
        self.records = records_of(self.stage1)
        self.episode = self.stage1.envelopes[0]["operation"]["episode_id"]
        self.stage2 = run(episode_records=self.records)

    # -- the design's own worked examples --------------------------------

    def test_the_two_same_binds_land_only_where_two_signals_exist(self):
        """§4.2's first worked example. ONE create, TWO `same` bindings, and
        the members are the landmark and the classifier occurrence that share
        a place AND a compatible date — nothing else in the story binds."""
        self.assertEqual(len(self.stage1.envelopes), 1)
        envelope = self.stage1.envelopes[0]
        self.assertEqual(envelope["operation"]["members"],
                         EXPECTED["etherfuse_bind_members"])
        self.assertEqual(len(envelope["bindings"]), 2)
        for row in envelope["bindings"]:
            self.assertEqual(row["relation"], efc.GROUPING_RELATION)
            self.assertEqual(row["origin"], "deterministic")
            self.assertEqual(row["rule_id"], eb.RULE_ID)
        pair = pair_of(self.stage1, ref("etherfuse_anchor"), ref("etherfuse_same"))
        self.assertEqual(
            sorted(eb.independent_signals(
                self.stage1.views[ref("etherfuse_anchor")],
                eb.candidates(self.stage1.views)[ref("etherfuse_same")])),
            ["bounds", "place"],
        )
        self.assertEqual(pair.failed(), ())

    def test_cofounded_is_a_proposal_because_only_one_signal_agrees(self):
        """§4.2's second worked example, byte for byte: the label stem matches
        and exactly one non-label signal does, so it is a PROPOSAL."""
        result = run("etherfuse_anchor", "etherfuse_same", "etherfuse_proposal")
        pair = pair_of(result, ref("etherfuse_proposal"), ref("etherfuse_anchor"))
        self.assertEqual(pair.verdict, "proposal")
        by_name = {row.name: row for row in pair.conditions}
        self.assertTrue(by_name["label_stems_match"].passed)
        self.assertEqual(by_name["label_stems_match"].detail,
                         f"{EXPECTED['cofounded_stem']} vs "
                         f"['{EXPECTED['etherfuse_stem']}']")
        self.assertFalse(by_name["two_independent_signals"].passed)
        self.assertEqual(by_name["two_independent_signals"].detail, "1 of 2: place")
        self.assertNotIn(ref("etherfuse_proposal"),
                         [row for envelope in result.envelopes
                          for row in envelope["operation"]["members"]])

    def test_the_idea_for_etherfuse_is_refused_by_the_kind_family_gate(self):
        """§13.3, verbatim: refused by the kind-family gate, and a QUESTION."""
        pair = pair_of(self.stage2, ref("etherfuse_asked"), self.episode)
        by_name = {row.name: row for row in pair.conditions}
        self.assertFalse(by_name["kind_family"].passed)
        self.assertEqual(by_name["kind_family"].detail, "idea vs job: no shared family")
        self.assertEqual(pair.verdict, "asked")
        keys = {row["event_key"] for row in self.stage2.questions}
        self.assertIn(pair.event_key, keys)

    # -- condition 2 -----------------------------------------------------

    def test_an_undated_telling_never_auto_binds_to_a_repeatable_episode(self):
        """§13.3's first binder promise. `job` is repeatable
        (`identity_resolution.REPEATABLE_EVENT_KINDS`); an undated telling
        carries none of the episode's discriminator evidence."""
        records = create_records(refs("ridgeline"), kind="job")
        result = run("ridgeline", "ridgeline_undated", episode_records=records)
        pair = direction_of(result, ref("ridgeline_undated"), records["episode_id"])
        by_name = {row.name: row for row in pair.conditions}
        self.assertFalse(by_name["repeatable_protection"].passed)
        self.assertNotEqual(pair.verdict, "bind")
        self.assertEqual(result.envelopes, [])

    def test_the_same_telling_dated_would_have_bound(self):
        """Proven to fire in both directions: the guard is the DATE, not the
        story — the identical telling with a date passes condition 2."""
        row = dict(tellings("ridgeline_undated")[0], dated="2015")
        claims = claims_for("ridgeline") + [telling_claim(row)]
        records = create_records(refs("ridgeline"), kind="job")
        result = eb.plan(claims, episode_records=as_input(records), frames=frames(), now=NOW)
        pair = direction_of(result, row["telling_ref"], records["episode_id"])
        by_name = {r.name: r for r in pair.conditions}
        self.assertTrue(by_name["repeatable_protection"].passed)
        self.assertEqual(pair.verdict, "bind")

    # -- condition 5 -----------------------------------------------------

    def test_two_surviving_candidates_yield_no_bind_and_one_item_naming_both(self):
        """§13.3. Three tellings of one join: nobody is the obvious partner,
        so nothing binds and every pair is asked with both candidates named."""
        result = run("ridgeline", "ridgeline_third")
        self.assertEqual(result.envelopes, [])
        pair = pair_of(result, ref("ridgeline"), ref("ridgeline_third"))
        by_name = {row.name: row for row in pair.conditions}
        self.assertFalse(by_name["one_surviving_candidate"].passed)
        self.assertEqual(by_name["one_surviving_candidate"].detail,
                         "2 candidate(s) survive conditions 1-4")
        self.assertEqual(pair.verdict, "ambiguous")
        # One item per PAIR, and the landmark is in two of them — named on
        # `units`, because after the two judged directions collapse a telling
        # is the row's `telling_ref` in only some of the pairs it is in.
        mine = [row for row in result.questions if ref("ridgeline") in row["units"]]
        self.assertEqual(len(mine), 2)
        partners = {side for row in mine for side in row["units"]} - {ref("ridgeline")}
        self.assertEqual(len(partners), 2)

    def test_two_of_the_same_three_do_bind(self):
        """Proven to fire: the SAME rows, one fewer rival, and R1 binds — so
        the refusal above is condition 5 and not the fixture."""
        result = run("ridgeline")
        self.assertEqual(len(result.envelopes), 1)
        self.assertEqual(result.envelopes[0]["operation"]["members"],
                         EXPECTED["ridgeline_bind_members"])

    # -- condition 6 -----------------------------------------------------

    def test_R1_never_binds_across_an_active_not_same(self):
        records = create_records(refs(*ETHERFUSE), kind="job")
        without = run("etherfuse_proposal", *ETHERFUSE, episode_records=records)
        self.assertEqual(
            verdict(without, ref("etherfuse_proposal"), records["episode_id"]),
            "proposal")
        blocked = dict(records)
        blocked["bindings"] = records["bindings"] + [
            human_binding(ref("etherfuse_proposal"), records["episode_id"], "not_same")
        ]
        result = run("etherfuse_proposal", *ETHERFUSE, episode_records=blocked)
        pair = pair_of(result, ref("etherfuse_proposal"), records["episode_id"])
        self.assertEqual(pair.verdict, "blocked")
        self.assertNotIn(pair.event_key,
                         {row["event_key"] for row in result.questions})

    def test_R1_never_binds_across_an_ENTAILED_not_same(self):
        """`same(A,E) ∧ not_same(B,E) ⇒ not_same(A,B)`, computed by C3 and
        never stored — so the negative disappears the moment a premise does."""
        records = create_records([ref("etherfuse_anchor")], kind="job")
        records = dict(records, bindings=records["bindings"] + [
            human_binding(ref("etherfuse_same"), records["episode_id"], "not_same")
        ])
        result = run(*ETHERFUSE, episode_records=records)
        # The ANCHOR's direction is the entailed one: it holds `same` to the
        # episode the other telling was declared different from, and nothing
        # is stored for that — C3 recomputes it every fold.
        entailed = direction_of(result, ref("etherfuse_anchor"), ref("etherfuse_same"))
        by_name = {row.name: row for row in entailed.conditions}
        self.assertFalse(by_name["no_not_same"].passed)
        self.assertEqual(by_name["no_not_same"].detail,
                         "an active or entailed not_same stands between them")
        # …and the pair the person would ever see is blocked, from either end.
        pair = pair_of(result, ref("etherfuse_same"), records["episode_id"])
        self.assertEqual(pair.verdict, "blocked")
        self.assertIn(
            tuple(sorted((ref("etherfuse_anchor"), ref("etherfuse_same")))),
            {tuple(sorted(row)) for row in efc.entailed_not_same(records["bindings"])},
        )

    # -- condition 7 -----------------------------------------------------

    def test_R1_never_joins_two_episodes_that_each_hold_two_or_more(self):
        """§13.3. Joining two mature episodes is a MERGE, and a merge is
        always human-confirmed in v1."""
        left = create_records(refs("ridgeline"), kind="job")
        right = create_records(refs("ridgeline_third", "ridgeline_undated"), kind="job")
        records = {"operations": left["operations"] + right["operations"],
                   "bindings": left["bindings"] + right["bindings"]}
        result = run("ridgeline", "ridgeline_third", "ridgeline_undated",
                     episode_records=records)
        pair = direction_of(result, ref("ridgeline"), right["episode_id"])
        by_name = {row.name: row for row in pair.conditions}
        self.assertFalse(by_name["not_joining_two_mature_episodes"].passed)
        self.assertEqual(result.envelopes, [])

    # -- Law 3 -----------------------------------------------------------

    def test_a_group_formed_by_transitivity_is_never_applied(self):
        """Law 3: union-find may propose and never apply. Two tellings that
        both chose one unit in one run are proposals, not a three-member
        episode nobody decided pairwise."""
        result = run("ridgeline", "ridgeline_third")
        self.assertEqual(result.envelopes, [])
        for pair in result.directional:
            self.assertNotEqual(pair.verdict, "bind")

    def test_a_different_label_refuses_a_bind_the_signals_would_have_allowed(self):
        """Condition 3 carries its own weight. Two tellings that agree on
        place AND date — two independent signals, everything else passing —
        still do not bind when they are not about the same act."""
        other = dict(tellings("etherfuse_same")[0],
                     telling_ref="classification:sold-story#aaaabbbbcccc",
                     mention="Sold Etherfuse", quote="Sold Etherfuse.")
        claims = claims_for("etherfuse_anchor") + [telling_claim(other)]
        result = eb.plan(claims, frames=frames(), now=NOW)
        pair = pair_of(result, other["telling_ref"], ref("etherfuse_anchor"))
        by_name = {row.name: row for row in pair.conditions}
        self.assertFalse(by_name["label_stems_match"].passed)
        self.assertTrue(by_name["two_independent_signals"].passed)
        self.assertNotEqual(pair.verdict, "bind")
        self.assertEqual(result.envelopes, [])

    def test_an_adopted_episode_is_never_grown_by_a_rule(self):
        """G1: a deterministic rule may file proposals against what a person
        acted on; it may never move it. The identical telling binds when the
        episode is unadopted (`test_the_same_telling_dated_would_have_bound`)
        and only proposes once somebody has renamed, dragged or placed it."""
        row = dict(tellings("ridgeline_undated")[0], dated="2015")
        claims = claims_for("ridgeline") + [telling_claim(row)]
        records = create_records(refs("ridgeline"), kind="job")
        adopted = dict(records, operations=records["operations"] + [
            ei.validate_episode_operation(ei.adopt_envelope(
                episode_id=records["episode_id"],
                creation_canonical_inputs=records["operations"][0]["canonical_inputs"],
                canonical_event_kind="job",
                source_ref="sources/conversations/msg-rename.md",
            ))
        ])
        result = eb.plan(claims, episode_records=as_input(adopted),
                         frames=frames(), now=NOW)
        pair = pair_of(result, row["telling_ref"], records["episode_id"])
        self.assertEqual([condition.name for condition in pair.conditions
                          if not condition.passed], [])
        self.assertEqual(pair.verdict, "proposal")
        self.assertEqual(result.envelopes, [])

    def test_a_bind_needs_both_sides_to_choose_each_other(self):
        for pair in self.stage1.directional:
            if pair.verdict != "bind":
                continue
            back = direction_of(self.stage1, pair.candidate_key, pair.telling_ref)
            self.assertEqual(back.verdict, "bind", "a bind was accepted one-sidedly")


# ==========================================================================
# §4.2 — deterministic `part_of`
# ==========================================================================


class ContainmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = create_records(refs(*ETHERFUSE), kind="job")
        self.episode = self.records["episode_id"]
        self.result = run(*ETHERFUSE, "etherfuse_part_of",
                          episode_records=self.records)

    def test_explicit_containment_language_in_the_tellings_own_words(self):
        """§4.2: the substring rule is DELETED. "during Etherfuse" is what
        makes this a containment; merely naming Etherfuse is not."""
        view = self.result.views[ref("etherfuse_part_of")]
        self.assertEqual(sorted(view.containment), ["etherfuse"])
        pair = pair_of(self.result, ref("etherfuse_part_of"), self.episode)
        self.assertEqual(pair.verdict, "part_of")
        self.assertEqual(pair.relation_hint, "part_of")

    def test_a_telling_that_only_mentions_the_name_is_not_contained(self):
        """Proven to fire: the same row without the phrase yields nothing."""
        row = dict(tellings("etherfuse_part_of")[0],
                   quote="We threw a big event in Mexico for Etherfuse.")
        claims = claims_for(*ETHERFUSE) + [telling_claim(row)]
        result = eb.plan(claims, episode_records=as_input(self.records), frames=frames(), now=NOW)
        self.assertEqual(result.views[row["telling_ref"]].containment, frozenset())
        self.assertNotEqual(verdict(result, row["telling_ref"], self.episode), "part_of")
        self.assertEqual(result.proposals, [])

    def test_the_record_is_a_proposal_because_C2_refuses_a_deterministic_part_of(self):
        """The one place §4.2 could not be honored as written. C2's validator
        pins the narrow reading — a `deterministic` origin binds `same` and
        nothing else — so containment lands as `proposed`, which changes no
        drawing (§2.3) and ranks the question."""
        self.assertEqual(len(self.result.proposals), 1)
        record = self.result.proposals[0]
        self.assertEqual(record["relation"], "part_of")
        self.assertEqual(record["origin"], "proposed")
        with self.assertRaises(ei.EventIdentityError) as caught:
            ei.validate_event_identity(dict(record, origin="deterministic"))
        self.assertEqual(caught.exception.code,
                         "identity_deterministic_relation_unsupported")

    def test_a_prospective_unit_is_never_a_container(self):
        """Proposing "this happened during that" about two tellings neither of
        which has been decided is two decisions wearing one record."""
        result = run(*ETHERFUSE, "etherfuse_part_of")
        for pair in result.pairs:
            if pair.candidate_kind == "prospective":
                self.assertNotEqual(pair.verdict, "part_of")

    def test_the_container_the_telling_named_must_be_the_WHOLE_name(self):
        """A subset, not an intersection. "during Ridgeline Labs" names
        Ridgeline Labs; an episode that is merely called Ridgeline is not
        what the sentence said."""
        row = dict(tellings("etherfuse_part_of")[0],
                   places=["Phoenix"], mention="Big Ridgeline party",
                   quote="We threw a party during Ridgeline Labs.")
        claims = claims_for("ridgeline") + [telling_claim(row)]
        records = create_records(refs("ridgeline"), kind="job")
        result = eb.plan(claims, episode_records=as_input(records),
                         frames=frames(), now=NOW)
        view = result.views[row["telling_ref"]]
        self.assertEqual(sorted(view.containment), ["labs", "ridgeline"])
        self.assertFalse(view.containment <= eb.candidates(
            result.views, episode_records=as_input(records))[records["episode_id"]].tokens)
        self.assertNotEqual(verdict(result, row["telling_ref"], records["episode_id"]),
                            "part_of")
        self.assertEqual(result.proposals, [])

    def test_two_containers_are_no_pick_at_all(self):
        """I1's own rule one layer up — and filing both would be
        `identity_conflict` on the next read, since `part_of` groups."""
        left = create_records(refs(*ETHERFUSE), kind="job")
        right = create_records(refs("etherfuse_proposal", "etherfuse_asked"), kind="job")
        records = {"operations": left["operations"] + right["operations"],
                   "bindings": left["bindings"] + right["bindings"]}
        row = dict(tellings("etherfuse_part_of")[0],
                   quote="A big event in Mexico during Etherfuse and during Etherfuse.")
        claims = claims_for(*ETHERFUSE, "etherfuse_proposal", "etherfuse_asked") \
            + [telling_claim(row)]
        result = eb.plan(claims, episode_records=as_input(records), frames=frames(), now=NOW)
        containers = [pair for pair in result.pairs
                      if pair.telling_ref == row["telling_ref"]
                      and pair.verdict == "part_of"]
        self.assertLessEqual(len(containers), 1)
        if len(containers) == 0:
            self.assertEqual(result.proposals, [])


# ==========================================================================
# §4.5 — the safeguards that ship WITH R1
# ==========================================================================


class SafeguardTests(unittest.TestCase):
    def test_disjoint_stated_bounds_mint_one_item_and_never_a_split(self):
        """§13.3. Two members whose own dates cannot both be true of one event
        is the over-merge signal — and the answer is a question, never an
        automatic split, which would be this design's own defect mirrored."""
        members = [ref("etherfuse_anchor"), ref("ridgeline")]
        records = create_records(members, kind="job")
        result = run("etherfuse_anchor", "ridgeline", episode_records=records)
        self.assertEqual(len(result.overmerges), 1)
        row = result.overmerges[0]
        self.assertEqual(row["kind"], eb.POSSIBLE_OVERMERGE_KIND)
        self.assertEqual(row["finding"], "disjoint_stated_bounds")
        self.assertEqual(row["telling_refs"], sorted(members))
        self.assertEqual(row["item_id"], eb.disjoint_bounds_item_id(
            episode_id=records["episode_id"], telling_refs=members))
        self.assertEqual(result.envelopes, [])
        for operation in result.as_dict()["envelopes"]:
            self.assertNotEqual(operation["operation"]["op"], "split")

    def test_compatible_bounds_mint_nothing(self):
        """Proven to fire: the same audit over an episode whose members agree
        says nothing at all."""
        records = create_records(refs(*ETHERFUSE), kind="job")
        result = run(*ETHERFUSE, episode_records=records)
        self.assertEqual(result.overmerges, [])

    def test_the_operation_graph_names_the_single_receipt(self):
        """§13.3. Articulation, computed over the operation graph: which one
        receipt is the only thing holding two halves of an episode together."""
        left = create_records(refs(*ETHERFUSE), kind="job")
        right = create_records(refs("ridgeline"), kind="job")
        merged = merge_records(left, right)
        rows = eb.bridge_diagnostics(as_input(merged))
        bridges = [row for row in rows if row["finding"] == "bridge"]
        self.assertTrue(bridges)
        self.assertIn(merged["merge_operation_id"],
                      {row["operation_id"] for row in bridges})
        for row in bridges:
            self.assertEqual(row["episode_id"], merged["episode_id"])
            self.assertEqual(len(row["members"]), 4)

    def test_a_sole_receipt_is_reported_and_is_not_a_bridge(self):
        """A diagnostic that fires on every episode is a diagnostic nobody
        reads: of course the only receipt is holding it together."""
        records = create_records(refs(*ETHERFUSE), kind="job")
        rows = eb.bridge_diagnostics(as_input(records))
        self.assertEqual([row["finding"] for row in rows], ["sole_receipt"])
        self.assertEqual(rows[0]["operation_id"], records["operation_id"])

    def test_time_decay_is_part_of_suggestive_and_never_a_veto(self):
        """§4.5. Two dated tellings far apart that name different places are
        what a relocation inside one long episode looks like — so the pair is
        FLAGGED for the question, not struck from it."""
        # Same cast, seven years and a continent apart. The cast is what
        # retrieves them; the place disagreement is what would have vetoed.
        anchor = dict(tellings("etherfuse_anchor")[0], participants=["AJ"])
        far = dict(tellings("etherfuse_same")[0], dated="2015", places=["Phoenix"],
                   participants=["AJ"])
        claims = ([birth_claim(), telling_claim(anchor)] + participant_claims(anchor)
                  + [telling_claim(far)] + participant_claims(far))
        result = eb.plan(claims, frames=frames(), now=NOW)
        pair = pair_of(result, far["telling_ref"], ref("etherfuse_anchor"))
        self.assertTrue(pair.part_of_suggestive)
        self.assertIn(pair.event_key, {row["event_key"] for row in result.questions})
        self.assertTrue(any(row["part_of_suggestive"] for row in result.questions))
        self.assertIn("part_of-suggestive", "\n".join(eb.describe_pair(pair)))

    def test_a_near_pair_is_not_flagged(self):
        anchor = dict(tellings("etherfuse_anchor")[0], participants=["AJ"])
        near = dict(tellings("etherfuse_same")[0], places=["Phoenix"],
                    participants=["AJ"])
        claims = ([birth_claim(), telling_claim(anchor)] + participant_claims(anchor)
                  + [telling_claim(near)] + participant_claims(near))
        result = eb.plan(claims, frames=frames(), now=NOW)
        self.assertFalse(
            pair_of(result, near["telling_ref"], ref("etherfuse_anchor")).part_of_suggestive)


# ==========================================================================
# §5.6 — the re-audit
# ==========================================================================


class ReauditTests(unittest.TestCase):
    def setUp(self) -> None:
        # A telling deterministically bound to one episode, and a second
        # episode that is now just as plausible a home for it: G3's own
        # arrival-order case.
        self.bound = create_records(refs(*ETHERFUSE), kind="job")
        self.rival = create_records(refs("etherfuse_proposal", "etherfuse_part_of"),
                                    kind="job")
        self.records = {
            "operations": self.bound["operations"] + self.rival["operations"],
            "bindings": self.bound["bindings"] + self.rival["bindings"],
        }
        self.result = run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                          episode_records=self.records)

    def test_a_new_candidate_mints_one_possible_overmerge_and_moves_nothing(self):
        minted = [row for row in self.result.reaudits
                  if row["action"] == erc.REAUDIT_MINT]
        self.assertTrue(minted)
        episodes = {self.bound["episode_id"], self.rival["episode_id"]}
        for row in minted:
            self.assertEqual(row["kind"], erc.POSSIBLE_OVERMERGE_KIND)
            self.assertIn(row["existing_bind"], episodes)
            self.assertIn(row["new_candidate"], episodes)
            self.assertNotEqual(row["existing_bind"], row["new_candidate"])
        mine = [row for row in minted if row["telling_ref"] == ref("etherfuse_anchor")]
        self.assertTrue(mine, "the bound telling itself was not re-audited")
        self.assertEqual(mine[0]["existing_bind"], self.bound["episode_id"])
        self.assertEqual(mine[0]["new_candidate"], self.rival["episode_id"])
        for row in self.result.reaudits:
            self.assertIn(row["action"], (erc.REAUDIT_MINT, erc.REAUDIT_NO_ACTION))
            self.assertNotIn(row["action"], erc.FORBIDDEN_REAUDIT_ACTIONS)
        # the bind is untouched
        for envelope in self.result.envelopes:
            self.assertNotIn(ref("etherfuse_anchor"), envelope["operation"]["members"])

    def test_every_enumerated_trigger_mints_or_does_nothing(self):
        """§5.6: the triggers are enumerated so none can be forgotten, and no
        trigger may reach any of :data:`FORBIDDEN_REAUDIT_ACTIONS`."""
        for trigger in erc.REAUDIT_TRIGGERS:
            result = run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                         episode_records=self.records, trigger=trigger)
            self.assertTrue(result.reaudits, f"{trigger} produced no re-audit at all")
            for row in result.reaudits:
                self.assertEqual(row["trigger"], trigger)
                self.assertIn(row["action"], (erc.REAUDIT_MINT, erc.REAUDIT_NO_ACTION))

    def test_an_unknown_trigger_is_refused(self):
        with self.assertRaises(Exception) as caught:
            run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                episode_records=self.records, trigger="a_new_idea")
        self.assertEqual(getattr(caught.exception, "code", ""),
                         "reaudit_unknown_trigger")

    def test_an_answered_pair_is_never_re_minted(self):
        answered = [{"telling_ref": ref("etherfuse_anchor"),
                     "candidate_episode_id": self.rival["episode_id"]}]
        result = run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                     episode_records=self.records, answered_pairs=answered)
        for row in result.reaudits:
            if row.get("telling_ref") == ref("etherfuse_anchor"):
                self.assertEqual(row["action"], erc.REAUDIT_NO_ACTION)

    def test_re_triggering_dedupes_on_the_pair(self):
        first = next(row for row in self.result.reaudits
                     if row["action"] == erc.REAUDIT_MINT)
        again = run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                    episode_records=self.records, open_items=[first["item_id"]])
        for row in again.reaudits:
            if row.get("item_id") == first["item_id"]:
                self.assertEqual(row["action"], erc.REAUDIT_NO_ACTION)


# ==========================================================================
# §6.1 — the outputs, the pair key and the caps
# ==========================================================================


class QuestionOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = run()

    def test_the_pair_key_is_C4s_and_is_never_re_spelled_here(self):
        """§6.1's `event_key` serializes the PAIR, and C4 owns the spelling."""
        for pair in self.result.pairs:
            self.assertEqual(pair.event_key, erc.pair_event_key(
                pair.telling_ref, pair.candidate_episode_id))
        for row in self.result.questions:
            self.assertEqual(row["event_key"], erc.pair_event_key(
                row["telling_ref"], row["candidate_episode_id"]))
            self.assertIn(erc.PAIR_KEY_SEPARATOR, row["event_key"])

    def test_a_prospective_candidate_is_named_by_the_id_a_yes_would_create(self):
        """The pair has to be nameable BEFORE anything exists — so it is named
        by arithmetic, and a later `yes` creates exactly the id that was
        asked about."""
        pair = pair_of(self.result, ref("etherfuse_proposal"), ref("etherfuse_anchor"))
        self.assertEqual(pair.candidate_kind, "prospective")
        self.assertEqual(pair.candidate_episode_id, eb.prospective_episode_id(
            sorted([ref("etherfuse_proposal"), ref("etherfuse_anchor")])))
        stage1 = run("etherfuse_proposal", "etherfuse_anchor")
        # …and R1 forming that very pair would mint that very episode.
        self.assertEqual(
            eb.prospective_episode_id(sorted([ref("etherfuse_proposal"),
                                              ref("etherfuse_anchor")])),
            ei.episode_id_for(ei.operation_digest(
                authority="deterministic", op="create", rule_version=eb.RULE_VERSION,
                member_refs=sorted([ref("etherfuse_proposal"), ref("etherfuse_anchor")]),
            )),
        )
        del stage1

    def test_at_most_one_pair_per_telling_is_surfaced(self):
        """§13.3: one pair per telling at a time; the rest stay eligible."""
        per_unit: dict = {}
        for row in self.result.questions:
            if row["surfaced"]:
                for side in row["units"]:
                    per_unit[side] = per_unit.get(side, 0) + 1
        self.assertTrue(per_unit)
        self.assertEqual(eb.SURFACED_PAIRS_PER_TELLING, 1)
        for side, count in per_unit.items():
            self.assertEqual(count, 1, side)
        # …and a telling with several candidates really does have several.
        self.assertGreater(self.result.counts["max_candidates_per_telling"], 1)

    def test_the_global_cap_holds_and_is_a_knob(self):
        self.assertEqual(eb.GLOBAL_QUESTION_CAP, 25)
        tight = run(question_cap=2)
        self.assertEqual(sum(1 for row in tight.questions if row["surfaced"]), 2)
        self.assertEqual(len(tight.questions), len(self.result.questions))

    def test_a_capped_pair_is_still_emitted_and_still_keyed(self):
        """Dropping it would make the cap a silent decision about which of a
        person's questions exist."""
        tight = run(question_cap=0)
        self.assertTrue(tight.questions)
        self.assertEqual(sum(1 for row in tight.questions if row["surfaced"]), 0)
        for row in tight.questions:
            self.assertTrue(row["event_key"])

    def test_a_negative_cap_is_refused(self):
        with self.assertRaises(eb.EpisodeBinderError) as caught:
            run(question_cap=-1)
        self.assertEqual(caught.exception.code, "binder_cap_out_of_range")

    def test_a_question_row_carries_scoring_INPUTS_and_no_score(self):
        """§4.1: identity pairs enter the EXISTING value scoring like every
        other kind; the binder supplies inputs and invents no priority."""
        row = self.result.questions[0]
        self.assertEqual(sorted(row["score_inputs"]),
                         ["candidate_is_dated", "candidate_member_count",
                          "label_match", "plausibility", "telling_recency"])
        for name in tp.WORK_ITEM_SCORE_FIELDS:
            self.assertNotIn(name, row)
            self.assertNotIn(name, row["score_inputs"])

    def test_a_bound_pair_is_never_also_a_question(self):
        keys = {row["event_key"] for row in self.result.questions}
        for pair in self.result.pairs:
            if pair.verdict in ("bind", "blocked"):
                self.assertNotIn(pair.event_key, keys)

    def test_both_new_kinds_are_registered_in_work_item_kinds_at_i3(self):
        """I2 asserted the ABSENCE here on purpose — registering a kind whose
        answer nothing can file is the silent under-delivery ADR 0021 exists
        to refuse. I3 (`identity_questions.py`) is what can now file an
        answer, so the absence becomes a positive registration
        (`tests/test_event_identity_i3_questions.py` owns the rest of I3's
        proof)."""
        self.assertIn(eb.SAME_EVENT_KIND, tp.WORK_ITEM_KINDS)
        self.assertIn(eb.POSSIBLE_OVERMERGE_KIND, tp.WORK_ITEM_KINDS)
        self.assertEqual(eb.SAME_EVENT_KIND, "same_event")
        self.assertIs(eb.POSSIBLE_OVERMERGE_KIND, erc.POSSIBLE_OVERMERGE_KIND)


# ==========================================================================
# §8 — the dry run
# ==========================================================================


class DryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = run()
        self.lines = eb.describe(self.result)
        self.text = "\n".join(self.lines)

    def test_it_says_it_wrote_nothing(self):
        self.assertIn("DRY RUN — nothing was written", self.text)
        self.assertIn("APPLIED", "\n".join(eb.describe(self.result, applied=True)))

    def test_every_pair_prints_every_one_of_the_seven_conditions(self):
        """§4.2's last sentence: per-pair REASONS, every rule that passed and
        failed — not counts alone."""
        for pair in self.result.pairs:
            block = "\n".join(eb.describe_pair(pair))
            for name in eb.R1_CONDITIONS:
                self.assertIn(name, block, f"{name} missing from a pair's reasons")
            self.assertIn("verdict:", block)
            self.assertIn("signals:", block)
        self.assertEqual(len(eb.R1_CONDITIONS), 7)

    def test_the_summary_carries_the_rollout_numbers(self):
        """§8.1's report: candidate count, proposed questions, max candidates
        per telling, and the WHEN items that would disappear."""
        for key in ("pairs", "max_candidates_per_telling", "questions",
                    "would_bind_episodes", "when_items_that_would_disappear",
                    "dropped_below_floor"):
            self.assertIn(f"{key}:", self.text)
        self.assertGreater(self.result.counts["max_candidates_per_telling"], 1)
        self.assertEqual(self.result.counts["when_items_that_would_disappear"], 1)

    def test_the_when_count_is_the_tellings_a_bind_would_stop_asking(self):
        """A `same`-bound telling is never asked WHEN — structurally (§6.2) —
        so the number is the members an apply would fold into somebody else's
        node."""
        joined = sum(len(row["operation"]["members"]) - 1 for row in self.result.envelopes)
        self.assertEqual(self.result.counts["when_items_that_would_disappear"], joined)


# ==========================================================================
# Determinism, and the writes
# ==========================================================================


def seed_vault(root: Path, claims) -> None:
    """Write the claims as ordinary extraction receipts, one per source."""
    by_source: dict = {}
    for claim in claims:
        key = (claim["source_ref"]["source_id"], claim["source_ref"]["revision"],
               claim["extractor_version"])
        by_source.setdefault(key, []).append(claim)
    for (_source_id, _revision, extractor), rows in sorted(by_source.items()):
        ts.write_receipt(root, {
            "source_ref": rows[0]["source_ref"],
            "extractor_version": extractor,
            "created_at": "2026-08-30T00:00:00Z",
            "claims": [dict(row) for row in rows],
        })
    ts.rebuild_active_index(root)


class VaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="i2-binder-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        seed_vault(self.root, claims_for())

    def _files(self) -> set:
        return {path.relative_to(self.root).as_posix()
                for path in self.root.rglob("*") if path.is_file()}

    def test_a_dry_run_writes_not_one_byte(self):
        before = self._files()
        outcome = eb.bind_episodes(self.root, apply=False, now=NOW)
        self.assertFalse(outcome["applied"])
        self.assertIsNone(outcome["filed"])
        self.assertEqual(self._files(), before)
        self.assertTrue(outcome["plan"].envelopes)

    def test_apply_files_through_event_identitys_own_writers(self):
        outcome = eb.bind_episodes(self.root, apply=True, now=NOW)
        self.assertTrue(outcome["applied"])
        self.assertEqual(len(outcome["filed"]["envelopes"]), 1)
        loaded = ef.load_episode_records(self.root)
        self.assertEqual(len(loaded["operations"]), 1)
        self.assertEqual(loaded["operations"][0]["authority"], "deterministic")
        self.assertEqual(loaded["operations"][0]["members"],
                         EXPECTED["etherfuse_bind_members"])
        for row in loaded["bindings"]:
            self.assertTrue(row["relative_path"].startswith(ei.STATE_BINDINGS_DIR))
        # The envelope reads back whole — never a partial episode.
        ei.load_operation_envelope(self.root, loaded["operations"][0])

    def test_an_applied_envelope_never_files_twice(self):
        """Replay is a no-op BY ARITHMETIC: the operation id digests semantic
        inputs, so the second run meets its own bytes and keeps them."""
        first = eb.bind_episodes(self.root, apply=True, now=NOW)
        second = eb.bind_episodes(self.root, apply=True, now="2027-01-01T00:00:00Z")
        # The two members are now ONE unit, so the pair is not even proposed
        # again — and had it been, the digest would have kept the first bytes.
        self.assertEqual(second["plan"].envelopes, [])
        self.assertEqual(len(first["filed"]["envelopes"]), 1)
        self.assertEqual(
            ef.load_episode_records(self.root)["operations"][0]["created_at"], NOW)

    def test_the_run_after_an_apply_converges_rather_than_repeating(self):
        """The second run is not identical, and that is CORRECT: the Mexico
        telling says it happened *during Etherfuse*, and until this run there
        was no Etherfuse episode for it to say that about. The third run,
        with nothing new to see, writes nothing at all."""
        eb.bind_episodes(self.root, apply=True, now=NOW)
        second = eb.bind_episodes(self.root, apply=True, now=NOW)
        self.assertEqual([row["telling_ref"] for row in second["plan"].proposals],
                         [ref("etherfuse_part_of")])
        self.assertEqual(second["filed"]["created"], 1)
        files = self._files()
        third = eb.bind_episodes(self.root, apply=True, now="2027-01-01T00:00:00Z")
        self.assertEqual(third["filed"]["created"], 0)
        self.assertEqual(self._files(), files)

    def test_delete_all_deterministic_state_and_re_run_is_byte_identical(self):
        """The G1 release promise, at the binder. The operation id digests
        semantic inputs only — no invocation id, no clock — so deleting every
        deterministic record and re-running on the same durable inputs lands
        on the same operation ids, episode ids and bindings."""
        import shutil

        eb.bind_episodes(self.root, apply=True, now=NOW)
        before = {
            path.relative_to(self.root).as_posix(): path.read_text("utf-8")
            for path in sorted((self.root / ei.IDENTITY_STATE_DIR).rglob("*.json"))
        }
        self.assertTrue(before)
        shutil.rmtree(self.root / ei.IDENTITY_STATE_DIR)
        eb.bind_episodes(self.root, apply=True, now="2031-02-03T04:05:06Z")
        after = {
            path.relative_to(self.root).as_posix(): path.read_text("utf-8")
            for path in sorted((self.root / ei.IDENTITY_STATE_DIR).rglob("*.json"))
        }
        self.assertEqual(sorted(before), sorted(after))
        for relative, text in before.items():
            self.assertEqual(
                ei.identity_assertion_view(json.loads(text)),
                ei.identity_assertion_view(json.loads(after[relative])),
                f"{relative} came back different after state deletion",
            )

    def test_the_bind_ends_the_when_questions_it_promised_to_end(self):
        """§8.1's headline number, checked against the fold that follows — so
        the rollout report is a MEASUREMENT and not a claim.

        The measure is the WHEN questions and not the node count, because
        §6.2's promise is about questions: `missing_anchor` is per node, so a
        `same`-bound telling stops being asked. (The node count does not fall
        by the same number here for a reason worth seeing: v264 already folds
        both landmark `job` tellings into ONE undiscriminated node, which is
        the very mess §1 diagnosed.)"""
        def fold(**kwargs):
            index = ts.fold_active_index(self.root)
            return tt.derive_calculated_timeline(
                {"version": index["version"],
                 "claims": [dict(row) for row in index["claims"]]},
                now=NOW, **kwargs)

        def when_questions(result) -> int:
            return len([row for row in result.work_items
                        if row.get("requested_field") == "date"])

        before = fold()
        promised = eb.bind_episodes(self.root, apply=False, now=NOW)["plan"]
        eb.bind_episodes(self.root, apply=True, now=NOW)
        after = fold(episode_records=ef.load_episode_records(self.root))
        self.assertEqual(when_questions(before) - when_questions(after),
                         promised.counts["when_items_that_would_disappear"])
        node = next(row for row in after.nodes if row.get("telling_count"))
        self.assertEqual(node["telling_count"], 2)
        self.assertEqual(node["tellings"], EXPECTED["etherfuse_bind_members"])

    def test_binder_step_is_a_dry_run_by_construction(self):
        """§8.3: no live bind before I3, so the SCHEDULED door cannot write."""
        before = self._files()
        outcome = eb.binder_step(self.root, now=NOW)
        self.assertFalse(outcome["wrote"])
        self.assertEqual(self._files(), before)
        self.assertTrue(outcome["counts"]["pairs"])
        self.assertIn("DRY RUN", "\n".join(outcome["report"]))


class DeterminismTests(unittest.TestCase):
    def test_two_runs_over_shuffled_claims_decide_the_same_thing(self):
        import random

        claims = claims_for()
        base = eb.plan(claims, frames=frames(), now=NOW)
        shuffled = list(claims)
        random.Random(11).shuffle(shuffled)
        other = eb.plan(shuffled, frames=frames(), now=NOW)
        self.assertEqual(json.dumps(base.as_dict(), sort_keys=True),
                         json.dumps(other.as_dict(), sort_keys=True))

    def test_the_run_is_a_pure_function_of_its_inputs(self):
        first = run()
        second = run()
        self.assertEqual(json.dumps(first.as_dict(), sort_keys=True),
                         json.dumps(second.as_dict(), sort_keys=True))


# ==========================================================================
# The hosts: one verb, one maintenance step, never inside `compile`
# ==========================================================================


class HostTests(unittest.TestCase):
    def test_the_verb_is_registered_the_way_its_siblings_are(self):
        """`bind-episodes` writes under the vault mutation lease when it
        applies, so it is classified BY NAME like `era-record` and
        `era-migrate` — a dry run is still classified, for the reason
        `focus-autopilot` is."""
        import lifehug

        self.assertIn("bind-episodes", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertTrue(hasattr(lifehug, "cmd_bind_episodes"))
        parser = lifehug.build_parser()
        args = parser.parse_args(["bind-episodes", "--dry-run"])
        self.assertIs(args.func, lifehug.cmd_bind_episodes)
        self.assertTrue(args.dry_run)
        self.assertFalse(parser.parse_args(["bind-episodes"]).apply)
        self.assertTrue(parser.parse_args(["bind-episodes", "--apply"]).apply)

    def test_dry_run_wins_when_both_flags_are_typed(self):
        """Muscle memory types `--apply` into a shell that already had
        `--dry-run` in it; the safe one has to win."""
        import lifehug

        args = lifehug.build_parser().parse_args(
            ["bind-episodes", "--dry-run", "--apply"])
        self.assertTrue(args.dry_run and args.apply)
        source = (ROOT / "system" / "lifehug.py").read_text("utf-8")
        self.assertIn(
            'apply = bool(getattr(args, "apply", False)) '
            'and not bool(getattr(args, "dry_run", False))',
            source,
        )

    def test_the_weekly_loop_runs_the_binder_and_runs_it_dry(self):
        """§13.3: the binder runs as a maintenance step. §8.3: not as a
        writer, until I3 exists."""
        script = (ROOT / "system" / "weekly_maintenance.sh").read_text("utf-8")
        self.assertIn("bind-episodes --dry-run", script)
        self.assertNotIn("bind-episodes --apply", script)
        self.assertIn("BINDER_OUT", script)

    def test_the_binder_never_runs_inside_compile(self):
        """§4: *"never inside `compile`"*. Proven by sweeping the modules
        `compile` actually reaches, not by reading the docstring."""
        for name in ("compose.py", "temporal_publication.py", "temporal_timeline.py",
                     "temporal_projection.py", "episode_fold.py",
                     "episode_fold_contract.py", "landmark_projection.py"):
            source = (ROOT / "system" / name).read_text("utf-8")
            self.assertNotIn("episode_binder", source, f"{name} reaches the binder")

    def test_the_new_module_is_a_framework_file(self):
        version = json.loads((ROOT / "system" / "version.json").read_text("utf-8"))
        self.assertIn("system/episode_binder.py", version["framework_files"])

    def test_the_shared_vocabulary_still_has_exactly_one_home(self):
        """ADR 0021, widened to a fourth module. C3 owns the words; the binder
        imports them, and `RULE_VERSION` is an alias rather than a copy."""
        import re

        program = ("episode_binder.py", "episode_fold_contract.py",
                   "episode_routing_contract.py", "event_identity.py")
        for name in ("IDENTITY_RULE_VERSION", "RELATIONS", "ORIGINS",
                     "GROUPING_RELATION", "GROUPING_ORIGINS"):
            pattern = re.compile(rf"^{name}\s*=", re.MULTILINE)
            homes = sorted(module for module in program
                           if pattern.search((ROOT / "system" / module).read_text("utf-8")))
            self.assertEqual(homes, ["episode_fold_contract.py"], name)
        self.assertIs(eb.RULE_VERSION, efc.IDENTITY_RULE_VERSION)
        self.assertIs(eb.POSSIBLE_OVERMERGE_KIND, erc.POSSIBLE_OVERMERGE_KIND)

    def test_every_refusal_the_module_raises_is_enumerated(self):
        """`temporal_claims.ERROR_CODES`' discipline, derived from source: a
        refusal nobody can enumerate is one a dashboard silently drops."""
        import ast

        tree = ast.parse((ROOT / "system" / "episode_binder.py").read_text("utf-8"))
        raised: set = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("_require", "EpisodeBinderError") and node.args:
                index = 1 if name == "_require" else 0
                literal = node.args[index] if len(node.args) > index else None
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    raised.add(literal.value)
        self.assertTrue(raised, "the AST sweep found no refusals at all")
        self.assertEqual(sorted(raised - set(eb.BINDER_ERROR_CODES)), [])

    def test_the_module_reads_no_real_vault(self):
        source = (ROOT / "system" / "episode_binder.py").read_text("utf-8")
        for forbidden in ("Workspace/dave", "lifehug/dave", "~/Workspace"):
            self.assertNotIn(forbidden, source)


# ==========================================================================
# The founder dry run's four findings (I2 live, 883 tellings)
# ==========================================================================


class LiveFindingTests(unittest.TestCase):
    """Every one of these is a defect the SYNTHETIC fixture could not show.

    The first live run against a real vault reported 4 164 "pairs" for 2 082
    pairs, `proposals: 0` beside `proposal=16`, and `age_frames: 0` on a vault
    holding a day-precision birthday. None of it was visible on a nine-telling
    fixture where every telling is a classifier telling with a place, a date
    and a sentence for a label. These tests carry the real shapes back.
    """

    # -- finding 1: one pair, one row ------------------------------------

    def test_a_pair_is_reported_once_and_judged_twice(self):
        result = run()
        self.assertEqual(len(result.directional), 2 * len(result.pairs))
        self.assertEqual(result.counts["directions_judged"], len(result.directional))
        self.assertEqual(result.counts["pairs"], len(result.pairs))
        seen = [row.units for row in result.pairs]
        self.assertEqual(len(seen), len(set(seen)), "a pair was reported twice")

    def test_one_pair_never_mints_two_items(self):
        result = run()
        keys = [row["event_key"] for row in result.questions]
        self.assertEqual(len(keys), len(set(keys)))
        by_units = [tuple(row["units"]) for row in result.questions]
        self.assertEqual(len(by_units), len(set(by_units)))

    def test_the_asymmetric_conditions_are_still_judged_both_ways(self):
        """The dedupe is a REPORTING rule. Four of R1's seven conditions read
        differently depending on which side is asking, and a pair that only
        looked one way would let an undated telling in through the direction
        that never meets the repeatable episode."""
        records = create_records(refs("ridgeline"), kind="job")
        result = run("ridgeline", "ridgeline_undated", episode_records=records)
        forward = direction_of(result, ref("ridgeline_undated"), records["episode_id"])
        self.assertFalse({row.name: row for row in forward.conditions}
                         ["repeatable_protection"].passed)
        pair = pair_of(result, ref("ridgeline_undated"), records["episode_id"])
        self.assertIn("repeatable_protection",
                      set(pair.failed()) | set(pair.also_failed))

    def test_a_refusal_in_either_direction_refuses_the_pair(self):
        self.assertEqual(eb.VERDICT_PRECEDENCE[-1], "bind")
        self.assertEqual(eb.VERDICT_PRECEDENCE[0], "blocked")
        rows = [
            eb.Pair(telling_ref="a:1", home_key="a:1", candidate_key="b:2",
                    candidate_episode_id="episode:" + "0" * 24,
                    candidate_kind="prospective", verdict="bind"),
            eb.Pair(telling_ref="b:2", home_key="b:2", candidate_key="a:1",
                    candidate_episode_id="episode:" + "0" * 24,
                    candidate_kind="prospective", verdict="asked"),
        ]
        units = {"a:1": eb.Candidate("a:1", "prospective", ("a:1",), "moment",
                                     frozenset(), frozenset(), frozenset(),
                                     frozenset(), frozenset(), frozenset()),
                 "b:2": eb.Candidate("b:2", "prospective", ("b:2",), "moment",
                                     frozenset(), frozenset(), frozenset(),
                                     frozenset(), frozenset(), frozenset())}
        collapsed = eb.collapse_directions(rows, units)
        self.assertEqual(len(collapsed), 1)
        self.assertEqual(collapsed[0].verdict, "asked")

    def test_collapsing_never_rewrites_a_judged_direction(self):
        """`directional` is the record of what each direction decided; a
        collapse that edited one in place would erase the asymmetry it exists
        to summarize."""
        records = create_records(refs("ridgeline"), kind="job")
        result = run("ridgeline", "ridgeline_undated", episode_records=records)
        # Identity, not equality: a copy that still compares equal is exactly
        # what we want, and `assertNotIn` would compare by value.
        for pair in result.pairs:
            self.assertFalse(any(pair is row for row in result.directional))

    def test_a_telling_against_an_existing_episode_is_the_canonical_direction(self):
        records = create_records(refs(*ETHERFUSE), kind="job")
        result = run(*ETHERFUSE, "etherfuse_proposal", episode_records=records)
        row = pair_of(result, ref("etherfuse_proposal"), records["episode_id"])
        self.assertEqual(row.telling_ref, ref("etherfuse_proposal"))
        self.assertEqual(row.candidate_key, records["episode_id"])
        self.assertEqual(row.candidate_kind, "episode")

    # -- finding 2: one tally --------------------------------------------

    def test_the_summary_and_the_verdict_line_come_from_one_tally(self):
        """The live run printed `proposals: 0` beside `proposal=16`. The two
        numbers counted different things under one word."""
        records = create_records(refs(*ETHERFUSE), kind="job")
        result = run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                     episode_records=records)
        counts = result.counts
        self.assertEqual(counts["proposal_pairs"], counts["verdicts"]["proposal"])
        self.assertEqual(counts["proposal_pairs"],
                         sum(1 for row in result.pairs if row.verdict == "proposal"))
        self.assertEqual(counts["part_of_records"], len(result.proposals))
        self.assertNotIn("proposals", counts)
        text = "\n".join(eb.describe(result))
        self.assertIn("proposal_pairs:", text)
        self.assertIn("part_of_records:", text)
        self.assertIn(f"proposal={counts['proposal_pairs']}", text)
        # The live shape, where the two numbers genuinely differ: proposals
        # without a single containment record. This is the state the founder's
        # own vault was in when the report said `proposals: 0` next to
        # `proposal=16`, so it is the state the guard has to be run against.
        live = run()
        self.assertEqual(live.counts["part_of_records"], 0)
        self.assertEqual(live.counts["proposal_pairs"],
                         live.counts["verdicts"]["proposal"])
        self.assertGreater(live.counts["proposal_pairs"], 1)
        self.assertNotEqual(live.counts["proposal_pairs"],
                            live.counts["part_of_records"])

    def test_the_two_fields_count_genuinely_different_things(self):
        """Proven by a state where they differ: a containment record and a
        proposal verdict are not the same event, which is why the old single
        word was a bug and not a typo."""
        records = create_records(refs(*ETHERFUSE), kind="job")
        result = run(*ETHERFUSE, "etherfuse_proposal", "etherfuse_part_of",
                     episode_records=records)
        self.assertEqual(result.counts["part_of_records"], 1)
        self.assertGreater(result.counts["proposal_pairs"], 0)
        # The containment record is not one of the proposal PAIRS: its own
        # pair is a `part_of`, and that is the whole point — the two fields
        # count different things and must never be one word again.
        part_of = [row for row in result.pairs if row.verdict == "part_of"]
        self.assertEqual(len(part_of), result.counts["part_of_records"])
        self.assertEqual(result.counts["verdicts"]["part_of"],
                         result.counts["part_of_records"])
        self.assertNotEqual(result.counts["verdicts"]["part_of"],
                            result.counts["proposal_pairs"] + 1)

    # -- finding 3: the frames are the fold's ----------------------------

    def test_the_frames_are_the_ones_the_fold_calculated(self):
        """One definition. The binder folds once and reads the answer; it does
        not own a second owner-birth predicate."""
        claims = claims_for()
        mine = eb.fold_age_frames(claims)
        folded = tt.derive_calculated_timeline(
            {"version": ts.INDEX_VERSION, "claims": [dict(row) for row in claims]},
        )
        self.assertTrue(mine)
        self.assertEqual([row.band for row in mine],
                         [row.band for row in folded.age_frames])

    def test_the_owner_birth_is_found_the_way_the_founder_vault_files_it(self):
        """The live defect, reproduced. The founder's own birth claim carries
        `subject_mention: "birth"` and NO `subject_ref` — subjects resolve
        inside the fold (v221) — so a predicate over raw claims that looked for
        `self`/`me`/`i` matched nothing and every frame went missing."""
        birth = _claim(
            claim_type="date", subject_mention="birth", event_kind="birth",
            source="landmark:entry-birth", quote="Born 11 July 1981.",
            temporal_value=_value(FIXTURE["owner_birth"]),
        )
        claims = [birth] + [telling_claim(row) for row in tellings(*ETHERFUSE)]
        frames_here = eb.fold_age_frames(claims)
        self.assertTrue(frames_here, "no age frames from a stated owner birthday")
        self.assertIn("childhood", [row.band for row in frames_here])

    def test_frames_come_from_claims_and_not_from_a_published_projection(self):
        """The fixture has no `state/temporal_claims/calculated-timeline.json`
        and never compiles one — the frames still arrive."""
        root = root_parent_tmp(self, ROOT, prefix="i2-frames-")
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "sources").mkdir(parents=True, exist_ok=True)
        seed_vault(root, claims_for())
        published = root / "state" / "temporal_claims" / "calculated-timeline.json"
        self.assertFalse(published.exists())
        outcome = eb.bind_episodes(root, apply=False, now=NOW)
        self.assertGreater(outcome["frames"], 0)
        self.assertFalse(published.exists(), "the binder published a projection")

    def test_no_birthday_means_no_frames_and_says_so(self):
        claims = [telling_claim(row) for row in tellings(*ETHERFUSE)]
        self.assertEqual(eb.fold_age_frames(claims), ())

    def test_the_bounds_signal_is_alive_once_the_frames_are(self):
        """The consequence the live run measured: with no frames the
        `bounds_in_frame` signal cannot fire on ANY pair."""
        views = eb.telling_views(claims_for())
        units = eb.candidates(views)
        pair = (ref("etherfuse_anchor"), ref("etherfuse_same"))
        with_frames = eb.retrieval_signals(views[pair[0]], units[pair[1]],
                                           frames=eb.fold_age_frames(claims_for()))
        self.assertIn("bounds_in_frame", with_frames)
        self.assertNotIn("bounds_in_frame",
                         eb.retrieval_signals(views[pair[0]], units[pair[1]], frames=()))

    # -- finding 4: the recorder's stem, and the honest floor -------------

    def test_a_recorder_telling_keeps_a_stem_after_the_cast_is_removed(self):
        """The live defect: a recorder telling's SUBJECT is the thing itself
        ("Etherfuse", started, 2022-05), so subtracting the cast erased the
        whole label and left a stem of `""` — and a telling with no stem
        matches nothing. Every dated landmark row on the founder's vault was
        unmatchable by construction."""
        self.assertEqual(eb.label_stem("Etherfuse", ["Etherfuse"]), "etherfuse")
        self.assertEqual(
            eb.label_stem("Etherfuse", ["Etherfuse"], event_kind="started"),
            EXPECTED["etherfuse_stem"],
        )
        # …and the cast is still removed when there is a label left without it.
        self.assertEqual(eb.label_stem("Co-founded Etherfuse with AJ", ["AJ"]),
                         EXPECTED["etherfuse_stem"])

    def test_the_act_is_read_from_the_kind_when_the_words_do_not_carry_it(self):
        """The recorder puts the act in `event_kind` and the classifier puts it
        in the sentence. One rule, read from wherever the source kind keeps
        it — and it makes a recorder stem MORE specific, never less."""
        self.assertEqual(eb.label_stem("Boeing", ["Boeing"], event_kind="job"),
                         "boeing")
        self.assertEqual(eb.label_stem("Katie", ["Katie"], event_kind="married"),
                         "katie-marry")
        self.assertTrue(eb.KIND_IS_THE_VERB_FOR_A_RECORDER_TELLING)

    def test_a_recorder_telling_and_a_classifier_telling_can_share_a_stem(self):
        """The whole point of §1: the DATED landmark and the undated classifier
        occurrence of one company must be able to match at all."""
        landmark = [
            _claim(claim_type="date", subject_mention="Etherfuse",
                   event_kind="started", source="landmark:entry-etherfuse-live",
                   quote="Started Etherfuse in May 2022.",
                   temporal_value=_value("2022-05")),
        ]
        views = eb.telling_views(landmark + [telling_claim(tellings("etherfuse_same")[0])])
        self.assertEqual(views["landmark:entry-etherfuse-live"].stem,
                         EXPECTED["etherfuse_stem"])
        self.assertEqual(views[ref("etherfuse_same")].stem, EXPECTED["etherfuse_stem"])

    def test_a_participant_that_is_only_the_label_again_is_not_a_second_signal(self):
        """Condition 4 says INDEPENDENT. On a recorder telling the subject is
        the label, so counting it as evidence beside a stem match would let one
        fact satisfy two signals — nine live pairs reported exactly that."""
        rows = [
            _claim(claim_type="date", subject_mention="Boeing", event_kind="job",
                   source=f"landmark:entry-boeing-{n}", quote="Boeing.",
                   temporal_value=_value(year))
            for n, year in enumerate(("1998", "2001"))
        ]
        views = eb.telling_views(rows)
        units = eb.candidates(views)
        left, right = sorted(views)
        self.assertIn("boeing", views[left].participants)
        self.assertNotIn("participant",
                         eb.independent_signals(views[left], units[right]))
        self.assertEqual(eb.independent_of_the_label(views[left], units[right]),
                         frozenset())

    def test_a_real_second_person_is_still_a_signal(self):
        """Proven in both directions: the rule drops the label wearing a
        participant's coat, never an actual participant."""
        rows = [
            _claim(claim_type="occurrence", subject_mention="AJ",
                   event_kind="moment", source=src, quote="With AJ.",
                   event_mention="Built the cabin with AJ")
            for src in ("classification:x#111111111111", "classification:y#222222222222")
        ]
        views = eb.telling_views(rows)
        units = eb.candidates(views)
        left, right = sorted(views)
        # The label keeps a subject of its own, so the cast is genuinely a
        # second fact rather than the same one wearing a participant's coat.
        self.assertEqual(views[left].stem, "cabin-build")
        self.assertEqual(eb.independent_of_the_label(views[left], units[right]),
                         frozenset({"aj"}))
        self.assertIn("participant", eb.independent_signals(views[left], units[right]))

    def test_zero_binds_is_what_this_floor_says_on_evidence_like_the_vaults(self):
        """The honest verdict, as a test rather than a paragraph.

        A stem match plus ONE independent signal is a proposal, not a bind —
        and on the founder's vault every one of the seventeen stem-matching
        pairs had exactly that. R1 is not mis-tuned here; it is refusing on
        purpose, and the question is what reaches the person.
        """
        rows = [
            _claim(claim_type="occurrence", subject_mention="I",
                   event_kind="moment", source=src, quote="Started Etherfuse.",
                   event_mention="Started Etherfuse", place_mentions=["Mexico City"])
            for src in ("classification:one#111111111111",
                        "classification:two#222222222222")
        ]
        result = eb.plan(rows, frames=frames(), now=NOW)
        pair = result.pairs[0]
        self.assertEqual(pair.verdict, "proposal")
        self.assertEqual(list(pair.failed()), ["two_independent_signals"])
        self.assertEqual(result.envelopes, [])
        self.assertEqual(
            {row.name: row for row in pair.conditions}
            ["two_independent_signals"].detail, "1 of 2: place")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
