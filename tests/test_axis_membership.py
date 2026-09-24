"""Whose moments ride the owner's axis (owner ruling 2026-09-23, v334).

ADR 0030 amendment. One deterministic rule at fold time — the person roster's
``relationship`` field and the owner's birth date — decides whether a moment
about somebody else is drawn on his axis, and every node publishes the answer
and the reason. The "About someone else" group (`contextual_only` read as a
Timeline surface) is retired.

Four tiers, one test class each:

* he lived it — ``owner`` / ``lived``, whoever else it is about (rule 1);
* immediate family's own event in his lifetime — ``family`` /
  ``immediate_family_in_lifetime`` (rule 2);
* anybody else's own event — ``none`` / ``not_family`` (rule 3);
* before his birth — ``none`` / ``pre_birth`` (rule 4, v324's rule kept).

AMENDED v338: rule 3 is a DECISION about a person whose relationship is KNOWN
to be outside the immediate family, and v334 let it swallow every subject whose
tier could not be read at all. Because ``not_family`` is what suppresses the
date question downstream, a loss whose person had no ``relationship`` on the
roster minted no "when?" card. The sixth reason ``relationship_unknown`` holds
that case, beside ``subject_unresolved``, and both keep their questions.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import axis_membership as axm  # noqa: E402
import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import era_memberships as era  # noqa: E402
import focus_candidate as fc  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402

BIRTH_DAY = "1981-07-11"
NOW = "2026-09-23T12:00:00Z"


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    source = overrides.pop("source", "src-conversation-1")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the conversation")}],
        "extractor_version": "listener:1",
        "created_at": "2026-09-23T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def dated(subject: str, best: str, *, event_kind: str = "graduation",
          source: str | None = None, mention: str | None = None) -> dict:
    return claim(
        claim_type="date",
        subject_mention=subject,
        event_mention=mention or f"{subject}'s {event_kind}",
        event_kind=event_kind,
        temporal_value=chrono.DateRecord(
            best=best, earliest=best, latest=best, granularity="day",
            confidence="certain", basis="stated",
        ).to_dict(),
        source=source or f"src-{subject}-{best}",
    )


def person_roster(*rows: dict) -> dict:
    return {"version": 1, "type": "person", "entities": list(rows)}


def roster_row(name: str, *, relationship: str | None = None,
               aliases: tuple[str, ...] = ()) -> dict:
    row: dict = {
        "name": name,
        "slug": name.casefold().replace(" ", "-").replace("'", ""),
        "aliases": list(aliases),
    }
    if relationship is not None:
        row["relationship"] = relationship
    return row


# ---------------------------------------------------------------------------
# The vocabulary — closed, total, and partitioned against the ONE shared list
# ---------------------------------------------------------------------------


class VocabularyTests(unittest.TestCase):

    def test_the_two_word_sets_partition_the_shared_relation_vocabulary(self) -> None:
        """Every word in `cross_dating.THIRD_PARTY_RELATION_WORDS` has a tier.

        That list is the one vocabulary the birth veto, the age veto and
        `temporal_timeline._mention_names_another_person` already read. A word
        added to it without being told which tier it belongs to would silently
        fall to `not_family`, which is the defect this assertion exists to
        prevent: the failure would be a moment leaving the owner's axis.
        """
        shared = {word.casefold() for word in cd.THIRD_PARTY_RELATION_WORDS}
        family = {w.casefold() for w in axm.IMMEDIATE_FAMILY_RELATION_WORDS}
        distant = {w.casefold() for w in axm.DISTANT_RELATION_WORDS}
        self.assertEqual(shared - (family | distant), set(),
                         "a shared relation word with no tier")
        self.assertEqual(family & distant, set(),
                         "a relation word claimed by both tiers")

    def test_the_roster_relationship_vocabulary_is_covered(self) -> None:
        """`focus_candidate.FOCUS_RELATIONSHIPS` is the roster's own closed list
        (`entity_verdict` enforces it); each value reads as exactly one tier."""
        for word in fc.FOCUS_RELATIONSHIPS:
            with self.subTest(word):
                self.assertIn(
                    axm.relationship_tier(word),
                    (axm.IMMEDIATE_FAMILY_TIER, axm.DISTANT_TIER),
                    f"{word!r} has no tier",
                )

    def test_the_closed_value_lists_are_exactly_the_ruling(self) -> None:
        self.assertEqual(tp.AXIS_MEMBERSHIPS, ("owner", "family", "none"))
        self.assertEqual(
            set(tp.AXIS_MEMBERSHIP_REASONS),
            {"lived", "immediate_family_in_lifetime", "pre_birth", "not_family",
             "subject_unresolved", "relationship_unknown"},
        )

    def test_only_the_rulings_two_decisions_take_a_node_off_the_axis(self) -> None:
        """v338. ``axis_membership: none`` has four reasons and only two of them
        are DECISIONS; the tuple every consequence site reads names exactly
        those two, and the two open questions are absent from it."""
        self.assertEqual(tp.AXIS_DECIDED_OFF_AXIS_REASONS,
                         ("not_family", "pre_birth"))
        for reason in ("relationship_unknown", "subject_unresolved"):
            with self.subTest(reason):
                self.assertNotIn(reason, tp.AXIS_DECIDED_OFF_AXIS_REASONS)
        self.assertTrue(
            set(tp.AXIS_DECIDED_OFF_AXIS_REASONS) <= set(tp.AXIS_MEMBERSHIP_REASONS))


# ---------------------------------------------------------------------------
# The tiers, from synthetic roster rows
# ---------------------------------------------------------------------------


class RosterTierTests(unittest.TestCase):

    def tier(self, roster: dict, subject: str) -> tuple[str, str]:
        return axm.subject_family_tier(
            subject, tier_index=axm.family_tier_index(roster)
        )

    def test_immediate_family_relationships_are_family(self) -> None:
        for word in ("spouse", "partner", "parent", "sibling", "grandparent",
                     "child", "grandchild"):
            with self.subTest(word):
                roster = person_roster(roster_row("Ruth", relationship=word))
                tier, basis = self.tier(roster, "person/ruth")
                self.assertEqual(tier, axm.IMMEDIATE_FAMILY_TIER)
                self.assertEqual(basis, "roster_relationship")

    def test_everybody_else_is_not_family(self) -> None:
        """The owner's own exclusions. An aunt, a cousin and a mother-in-law have
        no word of their own in the roster vocabulary, so they are recorded as
        ``other`` — and ``other`` is not immediate family."""
        for word in ("friend", "colleague", "mentor", "other"):
            with self.subTest(word):
                roster = person_roster(roster_row("Ruth", relationship=word))
                tier, basis = self.tier(roster, "person/ruth")
                self.assertEqual(tier, axm.DISTANT_TIER)
                self.assertEqual(basis, "roster_relationship")

    def test_cousins_aunts_and_in_laws_read_as_not_family_from_their_words(self) -> None:
        for name in ("Cousin Ruth", "Aunt Ruth", "Uncle Bob", "Ruth's nephew",
                     "my mother-in-law", "father in law"):
            with self.subTest(name):
                self.assertEqual(axm.relation_word_tier(name), axm.DISTANT_TIER)

    def test_an_in_law_is_never_family_however_the_phrase_is_built(self) -> None:
        """"mother-in-law" contains "mother" and is not the owner's mother."""
        self.assertEqual(axm.relation_word_tier("mother"), axm.IMMEDIATE_FAMILY_TIER)
        self.assertEqual(axm.relation_word_tier("mother-in-law"), axm.DISTANT_TIER)
        roster = person_roster(roster_row("Mother-in-law Pat"))
        self.assertEqual(self.tier(roster, "person/mother-in-law-pat")[0],
                         axm.DISTANT_TIER)

    def test_a_stated_relationship_beats_the_words_of_the_name(self) -> None:
        """The roster field is the OWNER'S OWN statement. An entity named
        "Grandma Betty Jo" whose relationship says ``friend`` is a friend."""
        roster = person_roster(
            roster_row("Grandma Betty Jo", relationship="friend")
        )
        self.assertEqual(self.tier(roster, "person/grandma-betty-jo"),
                         (axm.DISTANT_TIER, "roster_relationship"))

    def test_a_row_with_no_relationship_falls_to_its_own_name(self) -> None:
        """On the owner's vault only 2 of 11 person rows carry a
        ``relationship``, and the rest are titled "Grandma Betty Jo",
        "Parents", "Siblings", "Kids" — which is the owner's own word for the
        relation, written in the name field."""
        for name in ("Grandma Betty Jo", "Parents", "Siblings", "Kids",
                     "Son", "Daughter"):
            with self.subTest(name):
                roster = person_roster(roster_row(name))
                slug = name.casefold().replace(" ", "-")
                tier, basis = self.tier(roster, f"person/{slug}")
                self.assertEqual(tier, axm.IMMEDIATE_FAMILY_TIER)
                self.assertEqual(basis, "roster_name")

    def test_an_alias_reaches_the_same_tier_as_the_name(self) -> None:
        roster = person_roster(
            roster_row("Betty Jo Taylor", aliases=("Grandma", "Grandma BJ"))
        )
        index = axm.family_tier_index(roster)
        for key in ("person/betty-jo-taylor", "Betty Jo Taylor", "Grandma",
                    "grandma bj"):
            with self.subTest(key):
                self.assertEqual(
                    axm.subject_family_tier(key, tier_index=index)[0],
                    axm.IMMEDIATE_FAMILY_TIER,
                )

    def test_two_people_answering_to_one_alias_bind_to_neither(self) -> None:
        """The roster's own shared-alias rule (`roster_relations.alias_decision`):
        a key two rows disagree about is dropped rather than decided by file
        order."""
        roster = person_roster(
            roster_row("Ruth Taylor", relationship="sibling", aliases=("Ruth",)),
            roster_row("Ruth Nixon", relationship="friend", aliases=("Ruth",)),
        )
        index = axm.family_tier_index(roster)
        self.assertNotIn("ruth", index)
        self.assertEqual(index["person/ruth-taylor"][0], axm.IMMEDIATE_FAMILY_TIER)
        self.assertEqual(index["person/ruth-nixon"][0], axm.DISTANT_TIER)

    def test_a_name_nobody_stated_a_relation_for_is_unknown_not_distant(self) -> None:
        roster = person_roster(roster_row("Kodi Nixon"))
        self.assertEqual(self.tier(roster, "person/kodi-nixon"),
                         (axm.UNKNOWN_TIER, "none"))

    def reason(self, roster: object, subject: str, *,
               mention_texts: tuple[str, ...] = ()) -> str:
        """The PUBLISHED reason this roster and this subject reach, end to end.

        The three layers and the rule read together, because v338's defect lived
        in the seam between them: the tier came out right and the reason did
        not.
        """
        tier, _ = axm.subject_family_tier(
            subject, tier_index=axm.family_tier_index(roster),
            mention_texts=mention_texts,
        )
        return axm.axis_membership(
            occurrence_subject_scope="other_person",
            owner_timeline_relation="contextual_only",
            family_tier=tier, before_owner_birth=False,
        )[axm.AXIS_MEMBERSHIP_REASON_FIELD]

    def test_a_roster_row_with_no_relationship_reads_relationship_unknown(self) -> None:
        """v338, and the shape the hosted loss test handed in: one row, a name,
        a slug, and no ``relationship`` — which on the owner's own vault is 9 of
        11 person rows. Nobody has said who this is, so nothing is decided."""
        roster = person_roster(roster_row("Lumen Vasquez"))
        self.assertEqual(self.reason(roster, "person/lumen-vasquez"),
                         "relationship_unknown")

    def test_a_roster_row_that_says_friend_reads_not_family(self) -> None:
        """Rule 3's premise, stated: the relationship is KNOWN and outside the
        immediate set. This is the case v338 does NOT change."""
        roster = person_roster(roster_row("Lumen Vasquez", relationship="friend"))
        self.assertEqual(self.reason(roster, "person/lumen-vasquez"), "not_family")

    def test_a_mention_that_says_grandmother_is_family_with_no_roster_at_all(self) -> None:
        """The lexical layer still answers, and it answers FAMILY — the words
        are the owner's own statement of the relation."""
        self.assertEqual(axm.relation_word_tier("my grandmother"),
                         axm.IMMEDIATE_FAMILY_TIER)
        self.assertEqual(self.reason({}, "my grandmother"),
                         "immediate_family_in_lifetime")

    def test_a_bare_name_with_no_roster_at_all_reads_relationship_unknown(self) -> None:
        """No roster, no relation word, nothing in apposition: the honest answer
        is that nobody has said who this is. v334 called it ``not_family`` and
        took its question away."""
        for roster in ({}, (), person_roster()):
            with self.subTest(type(roster).__name__):
                self.assertEqual(self.reason(roster, "Lumen Vasquez"),
                                 "relationship_unknown")

    def test_the_roster_shapes_a_seat_may_hand_the_fold_all_work(self) -> None:
        row = roster_row("Ruth", relationship="sibling")
        for snapshot in (person_roster(row), [row], (person_roster(row),)):
            with self.subTest(type(snapshot).__name__):
                index = axm.family_tier_index(snapshot)
                self.assertEqual(index["person/ruth"][0], axm.IMMEDIATE_FAMILY_TIER)
        # A non-person roster contributes nothing: "Grandma Junction" is a place.
        self.assertEqual(
            axm.family_tier_index({"type": "place", "entities": [roster_row("Grandma Junction")]}),
            {},
        )


# ---------------------------------------------------------------------------
# The rule itself — pure, total, ordered as the owner stated it
# ---------------------------------------------------------------------------


class RuleTests(unittest.TestCase):

    def row(self, **kwargs) -> tuple[str, str]:
        defaults = {
            "occurrence_subject_scope": "other_person",
            "owner_timeline_relation": "contextual_only",
            "family_tier": axm.UNKNOWN_TIER,
            "before_owner_birth": False,
        }
        defaults.update(kwargs)
        out = axm.axis_membership(**defaults)
        return out["axis_membership"], out["axis_membership_reason"]

    def test_what_he_lived_is_his_whoever_else_it_is_about(self) -> None:
        """Rule 1, unchanged, and it outranks every other clause."""
        self.assertEqual(self.row(occurrence_subject_scope="owner",
                                  owner_timeline_relation="participated"),
                         ("owner", "lived"))
        for relation in tp.AXIS_RELATIONS:
            for tier in axm.FAMILY_TIERS:
                with self.subTest(relation=relation, tier=tier):
                    self.assertEqual(
                        self.row(owner_timeline_relation=relation, family_tier=tier),
                        ("owner", "lived"),
                    )

    def test_an_owner_occurrence_before_his_own_birth_stays_his(self) -> None:
        """A contradiction Mirror owns (`life_view: contradictory`), not family
        history — rule 4 is about OTHER people's events."""
        self.assertEqual(
            self.row(occurrence_subject_scope="owner",
                     owner_timeline_relation="participated",
                     before_owner_birth=True),
            ("owner", "lived"),
        )

    def test_immediate_family_in_his_lifetime_is_on_his_axis(self) -> None:
        self.assertEqual(self.row(family_tier=axm.IMMEDIATE_FAMILY_TIER),
                         ("family", "immediate_family_in_lifetime"))

    def test_a_known_relationship_outside_the_family_is_not_on_his_axis(self) -> None:
        """Rule 3, and AMENDED v338 to the tier it actually decides: the
        relationship must be KNOWN and outside the immediate set. Only
        `DISTANT_TIER` is that statement."""
        self.assertEqual(self.row(family_tier=axm.DISTANT_TIER),
                         ("none", "not_family"))

    def test_an_unknown_relationship_is_undecided_not_not_family(self) -> None:
        """THE v338 DEFECT, at the rule. Under v334 an unreadable tier came out
        ``not_family`` — rule 3's verdict, reached without rule 3's premise —
        and downstream that is the reason that suppresses the date question. The
        owner ruled (2026-09-23) that an unknown relationship is not that
        decision: it reads like ``subject_unresolved``. Same membership as rule 3
        (``none``: still not drawn on his axis until somebody says who this is),
        a reason of its own, and the questions stay."""
        self.assertEqual(self.row(family_tier=axm.UNKNOWN_TIER),
                         ("none", "relationship_unknown"))
        self.assertNotIn("relationship_unknown", tp.AXIS_DECIDED_OFF_AXIS_REASONS)

    def test_the_two_undecided_reasons_read_the_same_way(self) -> None:
        """Both are ``none``, and neither is one of the ruling's decisions —
        which is the whole of what v338 asserts about them."""
        unknown = self.row(family_tier=axm.UNKNOWN_TIER)
        unresolved = self.row(occurrence_subject_scope="unresolved",
                              owner_timeline_relation="unresolved")
        self.assertEqual(unknown[0], unresolved[0], "none")
        for _, reason in (unknown, unresolved):
            with self.subTest(reason):
                self.assertNotIn(reason, tp.AXIS_DECIDED_OFF_AXIS_REASONS)

    def test_before_his_birth_is_family_history(self) -> None:
        for tier in axm.FAMILY_TIERS:
            with self.subTest(tier):
                self.assertEqual(
                    self.row(family_tier=tier, before_owner_birth=True),
                    ("none", "pre_birth"),
                )

    def test_an_unidentified_subject_is_an_open_question_not_a_decision(self) -> None:
        self.assertEqual(
            self.row(occurrence_subject_scope="unresolved",
                     owner_timeline_relation="unresolved"),
            ("none", "subject_unresolved"),
        )

    def test_every_input_combination_lands_in_the_closed_lists(self) -> None:
        for scope in tp.OCCURRENCE_SUBJECT_SCOPES:
            for relation in tp.OWNER_TIMELINE_RELATIONS:
                for tier in axm.FAMILY_TIERS:
                    for before in (False, True):
                        membership, reason = self.row(
                            occurrence_subject_scope=scope,
                            owner_timeline_relation=relation,
                            family_tier=tier, before_owner_birth=before,
                        )
                        self.assertIn(membership, tp.AXIS_MEMBERSHIPS)
                        self.assertIn(reason, tp.AXIS_MEMBERSHIP_REASONS)

    def test_the_one_axis_predicate_answers_for_every_reader(self) -> None:
        self.assertTrue(axm.on_owner_axis({"axis_membership": "owner"}))
        self.assertTrue(axm.on_owner_axis({"axis_membership": "family"}))
        self.assertFalse(axm.on_owner_axis({"axis_membership": "none"}))

    def test_a_projection_written_before_the_ruling_reads_the_old_way(self) -> None:
        """Tolerant readers unaffected: a node with no ``axis_membership`` is one
        written by an older fold, and the honest reading of it is the axis test
        the page already had."""
        self.assertTrue(axm.on_owner_axis({"owner_timeline_relation": "lived_effect"}))
        self.assertFalse(axm.on_owner_axis({"owner_timeline_relation": "contextual_only"}))
        self.assertFalse(axm.on_owner_axis({}))


# ---------------------------------------------------------------------------
# The schema — additive, published as a pair, closed lists enforced
# ---------------------------------------------------------------------------


class SchemaTests(unittest.TestCase):

    def node(self, **extra) -> dict:
        payload = {
            "node_id": "node:aaaa",
            "node_kind": "event",
            "subject_refs": ["person/ruth"],
            "event_kind": "graduation",
            "best_temporal_value": None,
            "alternate_values": [],
            "input_claim_refs": ["claim:1"],
            "input_constraint_refs": [],
            "basis": "inferred",
            "confidence": 0.0,
            "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
            "projection_generation": 1,
            "conflict_state": "none",
        }
        payload.update(extra)
        return payload

    def test_a_node_without_the_pair_still_validates(self) -> None:
        row = tp.validate_calculated_timeline_node(self.node())
        self.assertNotIn("axis_membership", row)
        self.assertNotIn("axis_membership_reason", row)

    def test_the_pair_round_trips(self) -> None:
        row = tp.validate_calculated_timeline_node(self.node(
            axis_membership="family",
            axis_membership_reason="immediate_family_in_lifetime",
        ))
        self.assertEqual(row["axis_membership"], "family")
        self.assertEqual(row["axis_membership_reason"],
                         "immediate_family_in_lifetime")

    def test_a_value_outside_the_closed_list_is_refused(self) -> None:
        for payload, code in (
            ({"axis_membership": "sideways",
              "axis_membership_reason": "lived"}, "unknown_axis_membership"),
            ({"axis_membership": "family",
              "axis_membership_reason": "vibes"}, "unknown_axis_membership_reason"),
            ({"axis_membership": "family"}, "incomplete_axis_membership"),
            ({"axis_membership_reason": "lived"}, "incomplete_axis_membership"),
        ):
            with self.subTest(code):
                with self.assertRaises(tp.TimelineNodeError) as caught:
                    tp.validate_calculated_timeline_node(self.node(**payload))
                self.assertEqual(caught.exception.code, code)
                self.assertIn(code, tp.ERROR_CODES)


# ---------------------------------------------------------------------------
# The fold — published, and the surface it retires
# ---------------------------------------------------------------------------


class FoldTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-axis-membership-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)
        lp.file_landmark_record(self.vault, "birth", {
            "domain": "birth", "label": "birth",
            "date": {"best": BIRTH_DAY, "earliest": BIRTH_DAY, "latest": BIRTH_DAY,
                     "granularity": "day", "confidence": "certain",
                     "basis": "stated"},
        }, ordinal=1, now=NOW)

    def file_claims(self, claims) -> None:
        by_source: dict[tuple[str, str], tuple[dict, list[dict]]] = {}
        for row in claims:
            ref = row["source_ref"]
            key = (ref["source_id"], ref["revision"])
            by_source.setdefault(key, (ref, []))[1].append(dict(row))
        for ref, rows in by_source.values():
            ts.write_receipt(self.vault, {
                "source_ref": dict(ref),
                "extractor_version": "listener:1",
                "claims": rows,
            })

    def fold(self, *, roster_snapshot=()):
        return tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.vault),
            membership_assertions=era.active_era_memberships(self.vault),
            display_decisions=era.active_era_displays(self.vault),
            landmark_entries=lp.load_landmark_sources(self.vault),
            roster_snapshot=roster_snapshot,
            projection_generation=1,
            now=NOW,
        )

    def row(self, result, label_prefix: str) -> dict:
        for node in result.nodes:
            if str(node.get("label") or "").startswith(label_prefix):
                return node
        raise AssertionError(f"no node labelled {label_prefix!r}")

    def membership_ids(self, result) -> set:
        return {m["member_node_id"] for m in result.memberships}

    def date_items(self, result, node: dict) -> list:
        """Every ``precision_gap`` item about THIS node — the "when did this
        happen?" card, which is what v334 suppressed."""
        return [item for item in result.work_items
                if item.get("node_ref") == node["node_id"]
                and item.get("kind") == "precision_gap"]

    def findings(self, result) -> list:
        return [row.get("finding")
                for row in (result.diagnostics or {}).get("findings") or ()]

    def unplaced(self, result) -> list:
        return (result.diagnostics or {}).get("unplaced") or []


class FoldTests(FoldTestCase):

    def test_every_node_the_fold_scopes_publishes_the_pair(self) -> None:
        self.file_claims([dated("Mom", "1990-06-04")])
        result = self.fold()
        scoped = [n for n in result.nodes if n.get("owner_timeline_relation")]
        self.assertTrue(scoped)
        for node in scoped:
            with self.subTest(node["node_id"]):
                self.assertIn(node["axis_membership"], tp.AXIS_MEMBERSHIPS)
                self.assertIn(node["axis_membership_reason"],
                              tp.AXIS_MEMBERSHIP_REASONS)

    def test_a_relatives_own_milestone_in_his_lifetime_is_now_on_his_axis(self) -> None:
        """The whole ruling in one fold. Before v334 this node was
        `contextual_only` with no frame membership at all — the "About someone
        else" group. It is now drawn on his axis, as a moment about her, and it
        sits in the age frame its date falls in."""
        self.file_claims([dated("Mom", "1990-06-04")])
        result = self.fold()
        node = self.row(result, "Mom")
        self.assertEqual(node["owner_timeline_relation"], "contextual_only")
        self.assertEqual(node["axis_membership"], "family")
        self.assertEqual(node["axis_membership_reason"],
                         "immediate_family_in_lifetime")
        self.assertIn(node["node_id"], self.membership_ids(result))

    def test_the_roster_relationship_is_what_the_fold_reads(self) -> None:
        self.file_claims([dated("Ruth", "1990-06-04")])
        family = self.fold(roster_snapshot=person_roster(
            roster_row("Ruth", relationship="sibling")))
        distant = self.fold(roster_snapshot=person_roster(
            roster_row("Ruth", relationship="friend")))
        self.assertEqual(self.row(family, "Ruth")["axis_membership"], "family")
        self.assertEqual(self.row(distant, "Ruth")["axis_membership"], "none")
        self.assertEqual(self.row(distant, "Ruth")["axis_membership_reason"],
                         "not_family")

    def test_a_friends_own_event_is_not_on_his_axis_and_asks_nothing(self) -> None:
        """Rule 3, on the owner's own example — a friend's own move. It stays in
        the substrate (the node, its claims and its evidence are all still
        there) and it mints no owner-axis date question; the owner ruled there
        is no person-page question feature, so nothing is minted in its place.

        A KINDED milestone of theirs, because v324's scene rule is untouched: an
        unkinded `moment` out of his own telling is something he lived, and
        `test_a_scene_he_lived_stays_his_however_family_reads` pins that.
        """
        self.file_claims([claim(
            claim_type=tc.OCCURRENCE_CLAIM_TYPE, subject_mention="a friend",
            event_mention="a friend's move to Denver", event_kind="move",
            source="src-friend",
        )])
        result = self.fold()
        node = self.row(result, "a friend")
        self.assertEqual(node["axis_membership"], "none")
        self.assertEqual(node["axis_membership_reason"], "not_family")
        self.assertNotIn(node["node_id"], self.membership_ids(result))
        self.assertEqual(
            [item for item in result.work_items
             if item.get("node_ref") == node["node_id"]
             and item.get("kind") == "precision_gap"],
            [],
        )
        self.assertIn(node["node_id"], {n["node_id"] for n in result.nodes})
        self.assertNotIn(node["node_id"],
                         (result.diagnostics or {}).get("unplaced") or [])
        self.assertIn(
            "off_owner_axis_no_question",
            {row.get("finding") for row in (result.diagnostics or {}).get("findings") or ()},
        )

    def test_family_history_from_before_his_birth_stays_off_his_axis(self) -> None:
        """Rule 4, which is v324's own pre-birth rule under a name."""
        self.file_claims([dated("Grandma", "1932-09-16")])
        result = self.fold()
        node = self.row(result, "Grandma")
        self.assertEqual(node["axis_membership"], "none")
        self.assertEqual(node["axis_membership_reason"], "pre_birth")
        self.assertNotIn(node["node_id"], self.membership_ids(result))

    def test_a_scene_he_lived_stays_his_however_family_reads(self) -> None:
        """Rule 1 over rule 2: an unkinded moment out of his own telling is
        `lived_effect` and `owner`/`lived`, not `family` — the evidence that he
        lived it is the stronger fact, and v324's scene rule is untouched."""
        self.file_claims([dated("Grandma", "1995-04-02", event_kind="moment",
                                mention="Grandma died when I was in 9th grade")])
        result = self.fold()
        node = self.row(result, "Grandma")
        self.assertEqual(node["owner_timeline_relation"], "lived_effect")
        self.assertEqual(node["axis_membership"], "owner")
        self.assertEqual(node["axis_membership_reason"], "lived")

    def test_the_owners_own_moments_are_unchanged(self) -> None:
        self.file_claims([dated("self", "2001-09-11", event_kind="moment")])
        result = self.fold()
        owner_rows = [n for n in result.nodes
                      if n.get("occurrence_subject_scope") == "owner"]
        self.assertTrue(owner_rows)
        for node in owner_rows:
            with self.subTest(node["node_id"]):
                self.assertEqual(node["axis_membership"], "owner")
                self.assertEqual(node["axis_membership_reason"], "lived")

    def test_the_field_is_additive_and_nothing_else_moved(self) -> None:
        """Additive: the pair is the ONLY key the ruling adds to a node, and no
        existing key's value changes with it. Tolerant readers are unaffected."""
        self.file_claims([dated("Mom", "1990-06-04")])
        result = self.fold()
        node = self.row(result, "Mom")
        published = json.loads(json.dumps(node))
        self.assertEqual(
            set(published) - {"axis_membership", "axis_membership_reason"},
            set(published) - {"axis_membership", "axis_membership_reason"},
        )
        # The two E2 dimensions and their evidence are untouched by the ruling.
        self.assertEqual(published["occurrence_subject_scope"], "other_person")
        self.assertEqual(published["owner_timeline_relation"], "contextual_only")
        self.assertEqual(published["schema_version"], tp.projection_schema_version())

    def test_the_rule_version_moved_with_the_axis(self) -> None:
        """The same claims now calculate to a larger axis, so a projection
        folded by the old rules is detectably stale rather than merely wrong.

        v338 moves it again, to `:11`: an unknown-tier node publishes a
        different reason and keeps a work item it used to lose, which is the same
        kind of change and needs the same signal — a v334 projection is not
        merely mislabelled, it is missing cards.
        """
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:13")


# ---------------------------------------------------------------------------
# v338 — an unknown relationship is undecided, not "not family"
# ---------------------------------------------------------------------------


class UnknownRelationshipKeepsItsQuestionTests(FoldTestCase):
    """The v334 defect, at the fold, in the two shapes that caught it.

    Both were hosted tests on the platform's v334 pin (lifehug-platform PR
    #914, CI run 35920364976), ported here with synthetic names because the
    rule belongs to the framework and a defect the framework can reproduce
    should not need a host to notice it:

    * ``test_a_generic_loss_discovery_question_is_offer_only`` — a loss whose
      person is on the roster with no ``relationship``;
    * ``test_ordinary_answer_replans_old_stories_and_publishes_real_timeline``
      — the owner's own marriage, which names the spouse, and the spouse's
      roster row carries no ``relationship`` either.

    In both the tier is :data:`axis_membership.UNKNOWN_TIER`, v334 published
    ``not_family`` for it, and ``not_family`` is what suppresses the date
    question and drops the node from ``diagnostics["unplaced"]``.
    """

    #: The shape the hosted loss test hands in: a name, a slug, no relationship.
    LUMEN = {"slug": "synthetic-person-lumen", "name": "Synthetic Person Lumen"}

    def loss_of_lumen(self) -> dict:
        return claim(
            claim_type=tc.OCCURRENCE_CLAIM_TYPE,
            subject_mention="Synthetic Person Lumen",
            event_mention="Synthetic Person Lumen died.",
            event_kind="death",
            quote="Synthetic Person Lumen died.",
            source="src-lumen-loss",
        )

    def test_a_loss_whose_person_has_no_stated_relationship_keeps_its_date_question(self) -> None:
        """Hosted scenario 1. "Synthetic Person Lumen died." with one roster row
        and no ``relationship``: the ordinary contextual date question must be
        minted, on every surface. Under v334 it minted none."""
        self.file_claims([self.loss_of_lumen()])
        result = self.fold(roster_snapshot=person_roster(self.LUMEN))
        node = self.row(result, "Synthetic Person Lumen")
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["axis_membership"], "none")
        self.assertEqual(node["axis_membership_reason"], "relationship_unknown")
        self.assertEqual(len(self.date_items(result, node)), 1,
                         "the loss lost its 'when?' card")
        # And the node is the owner's own debt again: nothing was decided, so
        # something WILL be offered to him about it.
        self.assertIn(node["node_id"], self.unplaced(result))
        self.assertNotIn("off_owner_axis_no_question", self.findings(result))

    def test_the_owners_own_marriage_naming_the_spouse_keeps_its_date_question(self) -> None:
        """Hosted scenario 2, as its class rather than its fixture. The owner's
        own marriage is told by naming the spouse, the spouse is a roster person
        with no ``relationship``, so the node is ``other_person`` /
        ``contextual_only`` over an unknown tier — and under v334 the moment
        lost its work item entirely."""
        self.file_claims([claim(
            claim_type=tc.OCCURRENCE_CLAIM_TYPE,
            subject_mention="Rowan Vale",
            event_mention="Marriage to Rowan Vale",
            event_kind="married",
            quote="Marriage to Rowan Vale",
            source="src-marriage-rowan",
        )])
        result = self.fold(roster_snapshot=person_roster(
            {"slug": "rowan-vale", "name": "Rowan Vale"}))
        node = self.row(result, "Marriage to Rowan Vale")
        self.assertEqual(node["axis_membership_reason"], "relationship_unknown")
        self.assertEqual(len(self.date_items(result, node)), 1)
        self.assertIn(node["node_id"], self.unplaced(result))

    def test_saying_who_the_person_is_is_what_moves_the_node(self) -> None:
        """The same claims, three rosters: the relationship is the only input
        that moves, and each of the three answers is a different one. This is
        what makes ``relationship_unknown`` a WAITING state rather than a
        verdict — an answer that settles the relation settles the axis too."""
        self.file_claims([self.loss_of_lumen()])
        for relationship, membership, reason in (
            (None, "none", "relationship_unknown"),
            ("friend", "none", "not_family"),
            ("sibling", "family", "immediate_family_in_lifetime"),
        ):
            with self.subTest(relationship=relationship):
                row = dict(self.LUMEN)
                if relationship is not None:
                    row["relationship"] = relationship
                result = self.fold(roster_snapshot=person_roster(row))
                node = self.row(result, "Synthetic Person Lumen")
                self.assertEqual(node["axis_membership"], membership)
                self.assertEqual(node["axis_membership_reason"], reason)
                # ...and only the DECIDED one loses its card.
                self.assertEqual(
                    bool(self.date_items(result, node)),
                    reason != "not_family",
                )

    def test_a_friends_undated_event_still_keeps_no_card_without_leverage(self) -> None:
        """Rule 3 is untouched by v338, which is half of what makes it a fix
        rather than a revert: a KNOWN friend's own undated milestone is still off
        his axis, still mints no date question, and is still out of the unplaced
        cohort with the diagnostic to say so."""
        self.file_claims([claim(
            claim_type=tc.OCCURRENCE_CLAIM_TYPE, subject_mention="Lumen Vasquez",
            event_mention="Lumen Vasquez's move to Denver", event_kind="move",
            source="src-friend-move",
        )])
        result = self.fold(roster_snapshot=person_roster(
            roster_row("Lumen Vasquez", relationship="friend")))
        node = self.row(result, "Lumen Vasquez")
        self.assertEqual(node["axis_membership_reason"], "not_family")
        self.assertEqual(self.date_items(result, node), [])
        self.assertNotIn(node["node_id"], self.unplaced(result))
        self.assertIn("off_owner_axis_no_question", self.findings(result))

    def test_a_friends_undated_event_keeps_its_card_when_leverage_says_so(self) -> None:
        """The other half of rule 3, also untouched: dating a friend's event
        places one of the OWNER'S rows, so the date question is a question about
        his life phrased about theirs and it is minted after all."""
        self.file_claims([
            claim(claim_type=tc.OCCURRENCE_CLAIM_TYPE,
                  subject_mention="Lumen Vasquez",
                  event_mention="Lumen Vasquez's move", event_kind="move",
                  source="src-friend-move"),
            claim(claim_type="relative_order", subject_mention="self",
                  event_kind="moment", event_mention="the night I drove home",
                  temporal_value={"relation": "after",
                                  "anchors": ["Lumen Vasquez's move"]},
                  source="src-after-the-move"),
        ])
        result = self.fold(roster_snapshot=person_roster(
            roster_row("Lumen Vasquez", relationship="friend")))
        node = self.row(result, "Lumen Vasquez")
        self.assertEqual(node["axis_membership_reason"], "not_family")
        self.assertTrue(self.date_items(result, node),
                        "leverage should have kept the card")

    def test_family_history_from_before_his_birth_is_unchanged(self) -> None:
        """Rule 4, unchanged by v338 and asserted here because it is the other
        reason the suppression reads: a pre-birth node keeps no card and stays
        out of the unplaced cohort, whatever the relationship says."""
        self.file_claims([dated("Grandma", "1932-09-16")])
        result = self.fold()
        node = self.row(result, "Grandma")
        self.assertEqual(node["axis_membership_reason"], "pre_birth")
        self.assertEqual(self.date_items(result, node), [])
        self.assertNotIn(node["node_id"], self.unplaced(result))

    def test_the_diagnostic_names_only_the_decided_reasons(self) -> None:
        """`off_owner_axis_no_question` must stay ACCURATE: every one it reports
        carries one of the ruling's two decisions as its reason, never an open
        question dressed as a decision."""
        self.file_claims([
            self.loss_of_lumen(),
            claim(claim_type=tc.OCCURRENCE_CLAIM_TYPE, subject_mention="a friend",
                  event_mention="a friend's move to Denver", event_kind="move",
                  source="src-a-friend"),
            dated("Grandma", "1932-09-16"),
        ])
        result = self.fold(roster_snapshot=person_roster(self.LUMEN))
        reported = [row for row in (result.diagnostics or {}).get("findings") or ()
                    if row.get("finding") == "off_owner_axis_no_question"]
        self.assertTrue(reported)
        for row in reported:
            with self.subTest(row.get("node_ids")):
                self.assertIn(row.get("axis_membership_reason"),
                              tp.AXIS_DECIDED_OFF_AXIS_REASONS)
        # The unknown-relationship node is not among them.
        lumen = self.row(result, "Synthetic Person Lumen")
        self.assertNotIn(lumen["node_id"],
                         [node_id for row in reported
                          for node_id in row.get("node_ids") or ()])


class ManifestTests(unittest.TestCase):

    def test_the_new_files_ship_in_framework_files(self) -> None:
        manifest = json.loads((SYSTEM / "version.json").read_text())
        for name in ("system/axis_membership.py", "tests/test_axis_membership.py"):
            with self.subTest(name):
                self.assertIn(name, manifest["framework_files"])


if __name__ == "__main__":
    unittest.main()
