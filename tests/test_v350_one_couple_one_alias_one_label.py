"""v350 — one couple, one alias, one label.

Three defects the owner found on his own vault on 2026-09-24, all of them
visible in the same sweep and all three about a READING the substrate makes of
words somebody wrote.

1. **A couple is two people, not one relationship word.**
   `node:b8681112f7eed9342e7e4d56` *"Wedding reception in mother-in-law's
   backyard"* — the OWNER's reception, subject `self`, his own anniversary
   2007-01-11 — was folded into `node:536bdbed274f9512cc6c0378` at **1976-06-25**,
   his PARENTS' wedding, together with `claim:34c92ccbf218e122a181ca5f` (*"Mom
   married dad at 21"*) and `claim:e331cefd22c5a2c5670d861b` (*"Parents' wedding
   date"*). A roster introduction filed that morning had made ``mother`` an alias
   of `person/desiree-taylor`, and `episode_containers.resolve_entities` matches a
   contiguous token run — so the word ``mother`` INSIDE ``mother-in-law`` resolved
   to the owner's mother, the reception's person tokens became
   ``{desiree, taylor}``, and `R2b`'s per-person milestone bucket read the
   reception and the age telling as two tellings of one marriage. It surfaced as
   a contradiction card, so v340 held; the merge was still wrong.
   (:class:`ACompoundRelationIsNeverTheWordInsideItTests`,
   :class:`ACoupleIsReadFromTheSubjectsTests`,
   :class:`TheOwnersReceptionStaysHisOwnTests`.)

2. **An identity re-key publishes an alias.** v346 documented the seam and this
   closes it. A node id is derived from its subject, so the moment a roster
   introduction makes *"Dad graduated"* resolve to `person/james-taylor` the node
   moves — `node:1bdbc9ecc7305d5a90c6e4a4` (1987) became
   `node:2156ca1018344c8248882c44` (1987) for the identical claim
   `claim:cd8e993b6bf95a5f4c80c862` — and NO redirect was published, so the
   v340/v342 audit read it as a lost placement and every card and URL naming the
   old id broke. The same seam drew *"Mom babysat Kodi and Acey Nixon"* twice:
   the resolver reading of that stay carries the old id frozen in its own
   `event_ref`, so the derived key moved and the dated node and an undated copy of
   it stood side by side, the copy carrying a *"when?"* card the node beside it
   answers. (:class:`AnIdentityReKeyIsAWayANodeIdMovesTests`,
   :class:`TheReKeyLosesNoPlacementTests`.)

3. **A card never shows a node id as its label.** `question_planner` minted
   `missing_anchor` items whose whole question was *"When was
   node:0809d05e26d18f128fd83126?"* — 28 such cards on the hosted head, 22 of
   them with an id in the prompt, 10 after the sweep — because a cross-dating
   anchor may be a node ref and the composer asked about whatever text it was
   handed. Every one of the 48 nodes waiting on those anchors already carried a
   card of its own. (:class:`ACardNeverShowsANodeIdAsItsLabelTests`,
   :class:`TheAnchorSentenceIsGrammarTests`.)

`CALCULATION_RULE_VERSION` moves to ``timeline-rules:17``: nodes, aliases and
cards all change for a vault nobody edited.

Every negative below was run against a build with its guard removed and SEEN
failing first.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import axis_membership as axm  # noqa: E402
import chronology as chrono  # noqa: E402
import conversation_lints as cl  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_timeline as tt  # noqa: E402

# The v340 fixtures, reused rather than re-derived, for the reason v342 and v345
# reused them: a second spelling of "the shape a vault's receipts actually have"
# is how two tests come to disagree about what a vault is.
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    index_of,
    value,
)
from test_v345_a_telling_of_a_landmark_folds_onto_it import (  # noqa: E402
    placement_audit,
)

OWNER = tt.DEFAULT_OWNER_REF

# --------------------------------------------------------------------------
# The owner's own shapes
# --------------------------------------------------------------------------

#: `state/entity_rosters/person.json` after the 2026-09-24 sweep's
#: `entity-roster --ensure-introduced`, reduced to the rows that decide these
#: tests. ``mother`` and ``father`` as bare aliases are the introduction's own
#: work and the reason the reception broke.
ROSTER = {
    "version": 1,
    "type": "person",
    "entities": [
        {"name": "Desiree Taylor", "slug": "desiree-taylor",
         "relationship": "parent",
         "aliases": ["Desiree Taylor (Desi)", "Desi", "mom", "my mom",
                     "mother", "my mother"]},
        {"name": "James Taylor", "slug": "james-taylor",
         "relationship": "parent",
         "aliases": ["James Taylor (Dad)", "dad", "my dad",
                     "father", "my father"]},
    ],
}

#: The same roster with the mother-in-law introduced BY THAT PHRASE, which is
#: what proves the guard refuses the word inside a compound and not the compound.
ROSTER_WITH_AN_IN_LAW = {
    "version": 1,
    "type": "person",
    "entities": [
        *ROSTER["entities"],
        {"name": "Ruth Merrill", "slug": "ruth-merrill", "relationship": "other",
         "aliases": ["mother-in-law", "my mother-in-law"]},
    ],
}

RECEPTION_DAY = "2007-01-11"
PARENTS_WEDDING_DAY = "1976-06-25"
RECEPTION_LABEL = "Wedding reception in mother-in-law's backyard"

#: `answers/A54.md` — the reception, told by the owner about himself.
RECEPTION_TELLING = "classification:answers-a54#c00c85d2ac55"
#: `resolver:c1c89b8bf826c785b290fc46` — the resolver's dated reading of it.
RECEPTION_RESOLVER = "resolver:c1c89b8bf826c785b290fc46"
#: `answers/Q4.md` — his parents' wedding, stated to the day.
PARENTS_TELLING = "classification:answers-q4#12f78de35a22"
#: `answers/K14.md` — the age, and no date at all.
AGE_TELLING = "classification:answers-k14#0965c15bc3c2"


def reception_occurrence() -> dict:
    """`claim:efdfebf14c111436f1ecdefd`, in its own shape: an undated
    occurrence whose subject is the OWNER and whose label names a relation."""
    return claim(claim_type="occurrence", subject_mention="self",
                 event_kind="moment", source=RECEPTION_TELLING,
                 event_mention=RECEPTION_LABEL,
                 quote="Reception held at Katie's mom's backyard with cake "
                       "from Clayton Jumper")


def reception_date() -> dict:
    """`claim:6b34a63bd5e81603f66a9f3a`, the resolver's reading: the same label,
    the owner's own anniversary, stated to the day."""
    return claim(claim_type="date", subject_mention="self",
                 event_kind="moment", source=RECEPTION_RESOLVER,
                 temporal_value=value(RECEPTION_DAY),
                 event_mention=RECEPTION_LABEL,
                 quote="spine: Married Katie Ann Merrill: 11 January 2007 | "
                       "story: We had the reception in Katie's mom's backyard")


def parents_wedding() -> dict:
    """`claim:e331cefd22c5a2c5670d861b`."""
    return claim(claim_type="date", subject_mention="Author's parents",
                 event_kind="moment", source=PARENTS_TELLING,
                 temporal_value=value(PARENTS_WEDDING_DAY),
                 event_mention="Parents' wedding date",
                 quote="The author's parents were married on June 25, 1976.")


def age_telling() -> dict:
    """`claim:34c92ccbf218e122a181ca5f` — an age, about the MOTHER, undated."""
    return claim(claim_type="age", subject_mention="mother",
                 event_kind="moment", source=AGE_TELLING,
                 temporal_value="21", event_mention="Mom married dad at 21",
                 quote="Mom got married young, at age 21, and had kids right away")


def the_three_tellings() -> list[dict]:
    """The owner's own shape: his reception beside his parents' wedding."""
    return [reception_occurrence(), reception_date(),
            parents_wedding(), age_telling()]


def views_of(claims, *, roster=ROSTER) -> dict:
    index = ec.entity_index({"person": roster})
    return eb.telling_views(claims, entity_index=index)


def derive(claims, *, roster=(), **kwargs) -> object:
    return tt.derive_calculated_timeline(
        index_of(claims), roster_snapshot=roster, now=NOW, **kwargs
    )


def node_at(result, node_id: str) -> dict | None:
    for node in result.nodes:
        if node["node_id"] == node_id:
            return node
    return None


def nodes_labelled(result, label: str) -> list[dict]:
    return [node for node in result.nodes if node.get("label") == label]


def findings_named(result, name: str) -> list[dict]:
    return [row for row in result.diagnostics.get("findings") or ()
            if row.get("finding") == name]


def items_of(result, kind: str) -> list[dict]:
    return [row for row in result.work_items if row["kind"] == kind]


# ==========================================================================
# 1 — A COUPLE IS TWO PEOPLE, NOT ONE RELATIONSHIP WORD
# ==========================================================================


class ACompoundRelationIsNeverTheWordInsideItTests(unittest.TestCase):
    """`ident.A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT`, at the seat that
    resolved the wrong person."""

    def setUp(self):
        self.index = ec.entity_index({"person": ROSTER})

    def test_the_owners_own_label_resolves_nobody(self):
        """The whole defect in one assertion."""
        self.assertEqual(ec.resolve_entities(RECEPTION_LABEL, self.index),
                         frozenset())

    def test_the_bare_relationship_word_still_resolves(self):
        """The guard narrows one run and nothing else: a roster introduction is
        exactly what makes "mother" mean somebody, and it still does."""
        for text in ("mother", "my mother", "Mom married dad at 21 — mother"):
            with self.subTest(text=text):
                self.assertEqual(ec.resolve_entities(text, self.index),
                                 frozenset({"person/desiree-taylor"}))

    def test_every_compound_spelling_a_person_writes(self):
        for text in ("mother-in-law", "mother in law", "my mother-in-law",
                     "mothers-in-law", "step-mother", "step mother",
                     "grand-mother", "great-grandmother", "ex-wife",
                     "foster father", "half brother", "godmother",
                     "Wedding reception in mother-in-law's backyard"):
            with self.subTest(text=text):
                self.assertEqual(ec.resolve_entities(text, self.index),
                                 frozenset())

    def test_a_longer_key_is_the_compound_and_still_matches(self):
        """A roster that knows a mother-in-law BY THAT PHRASE resolves her by
        it — the guard answers only about a run that is one simple word."""
        index = ec.entity_index({"person": ROSTER_WITH_AN_IN_LAW})
        self.assertEqual(ec.resolve_entities(RECEPTION_LABEL, index),
                         frozenset({"person/ruth-merrill"}))
        self.assertEqual(ec.resolve_entities("my mother", index),
                         frozenset({"person/desiree-taylor"}))

    def test_a_name_is_untouched_by_the_guard(self):
        for text in ("Desiree Taylor", "Desi", "James Taylor in law"):
            with self.subTest(text=text):
                self.assertTrue(ec.resolve_entities(text, self.index))

    def test_the_token_predicate_answers_only_about_a_one_word_run(self):
        tokens = ("wedding", "reception", "in", "mother", "in", "law", "s", "backyard")
        self.assertTrue(ident._not_a_simple_relation(tokens, 3, 4))  # noqa: SLF001
        # The compound run itself is not refused, and neither is a non-relation.
        self.assertFalse(ident._not_a_simple_relation(tokens, 3, 6))  # noqa: SLF001
        self.assertFalse(ident._not_a_simple_relation(tokens, 0, 1))  # noqa: SLF001
        self.assertFalse(ident._not_a_simple_relation(tokens, 7, 8))  # noqa: SLF001

    def test_a_plural_relation_word_is_read_as_the_word(self):
        self.assertEqual(ident.relation_word_stem("parents"), "parent")
        self.assertEqual(ident.relation_word_stem("mother"), "mother")
        self.assertEqual(ident.relation_word_stem("brothers"), "brother")

    def test_a_longer_word_is_not_the_word_inside_it(self):
        """v347's own rule, restated: whole-token in both directions."""
        for word in ("grandson", "childhood", "motherhood", "brotherly"):
            with self.subTest(word=word):
                self.assertEqual(ident.relation_word_stem(word), "")

    def test_the_in_law_reading_is_one_object_in_both_modules(self):
        """It moved to `identity_resolution` and `axis_membership` re-exports
        it, so there is one regex rather than two that agree today."""
        self.assertIs(axm.IN_LAW_RE, ident.IN_LAW_RE)

    def test_the_rule_is_written_down(self):
        text = ident.A_COMPOUND_RELATION_IS_NEVER_THE_WORD_INSIDE_IT
        self.assertIn("mother-in-law", text)
        self.assertIn("never the simple word inside", text)


class ACoupleIsReadFromTheSubjectsTests(unittest.TestCase):
    """`ident.couple_key`, over the telling's own subjects."""

    def test_v345s_own_vocabulary_still_names_the_couple(self):
        for subjects, expected in (
            (("mother",), "couple:parents"),
            (("parents",), "couple:parents"),
            (("mom", "dad"), "couple:parents"),
            (("father",), "couple:parents"),
            (("Author's parents",), "couple:parents"),
            (("my mom",), "couple:parents"),
            (("mommy",), "couple:parents"),
            (("wife",), "couple:spouse"),
        ):
            with self.subTest(subjects=subjects):
                self.assertEqual(ident.couple_key(subjects), expected)

    def test_the_owners_own_subject_names_the_owners_couple(self):
        """The leg the reception needed: a telling about the owner belongs to
        HIS couple, whatever relationship word its label happens to carry."""
        for subjects in (("self",), ("me",), ("narrator",), ("self", "we")):
            with self.subTest(subjects=subjects):
                self.assertEqual(ident.couple_key(subjects), "couple:spouse")

    def test_a_compound_relation_subject_names_no_couple(self):
        for subjects in (("mother-in-law",), ("my mother-in-law",),
                         ("step-mother",), ("grandmother",),
                         ("father in law",)):
            with self.subTest(subjects=subjects):
                self.assertEqual(ident.couple_key(subjects), "")

    def test_a_name_is_no_couple_and_neither_is_a_mixed_set(self):
        for subjects in (("katie",), ("mother", "katie"), (), ("grandparents",),
                         ("self", "mother")):
            with self.subTest(subjects=subjects):
                self.assertEqual(ident.couple_key(subjects), "")

    def test_the_relation_word_a_subject_states(self):
        self.assertEqual(ident.couple_relation_word("Author's parents"), "parents")
        self.assertEqual(ident.couple_relation_word("my mom"), "mom")
        self.assertEqual(ident.couple_relation_word("mother-in-law"), "")
        self.assertEqual(ident.couple_relation_word("step mother"), "")
        self.assertEqual(ident.couple_relation_word("Katie"), "")

    def test_the_owner_couple_is_the_spouse_couple(self):
        self.assertEqual(ident.OWNER_COUPLE, "spouse")
        self.assertIn(ident.OWNER_COUPLE, set(ident.COUPLE_OF_RELATION_WORD.values()))

    def test_the_rules_are_written_down(self):
        self.assertIn("own SUBJECTS", ident.A_COUPLE_IS_READ_FROM_THE_TELLINGS_OWN_SUBJECTS)
        self.assertIn("two people", eb.A_COUPLE_IS_TWO_PEOPLE)
        self.assertIn("mother-in-law is not mother", eb.A_COUPLE_IS_TWO_PEOPLE)


class TheOwnersReceptionStaysHisOwnTests(unittest.TestCase):
    """The real shape, on a synthetic vault: the reception beside the parents'
    wedding, and they must stay two nodes."""

    def setUp(self):
        self.views = views_of(the_three_tellings())
        self.links = eb.milestone_links(self.views)

    def test_the_reception_is_about_the_owner_and_names_nobody_else(self):
        for ref in (RECEPTION_TELLING, RECEPTION_RESOLVER):
            with self.subTest(ref=ref):
                view = self.views[ref]
                self.assertEqual(view.label, RECEPTION_LABEL)
                self.assertEqual(eb.milestone_of(view), "married")
                self.assertEqual(view.subject_mentions, ("self",))
                self.assertEqual(view.people, frozenset())
                self.assertEqual(ident.couple_key(view.subject_mentions),
                                 "couple:spouse")

    def test_no_rung_binds_the_reception_to_the_parents_wedding(self):
        pairs = {frozenset((link.left, link.right)) for link in self.links}
        for reception in (RECEPTION_TELLING, RECEPTION_RESOLVER):
            for theirs in (PARENTS_TELLING, AGE_TELLING):
                with self.subTest(left=reception, right=theirs):
                    self.assertNotIn(frozenset((reception, theirs)), pairs)

    def test_v345s_own_pair_still_meets_across_two_vocabularies(self):
        """The couple rung is not weakened — and under a resolved roster it is
        RESTORED: the age telling's person tokens became `{desiree, taylor}`
        once the introduction landed, so the old people-side key had already
        stopped finding the couple it was written for."""
        keys = {link.key for link in self.links
                if {link.left, link.right} == {AGE_TELLING, PARENTS_TELLING}}
        self.assertEqual(keys, {"married:couple:parents"})

    def test_the_two_weddings_are_two_nodes_at_their_own_dates(self):
        result = derive(the_three_tellings(), roster=ROSTER)
        report = placement_audit(result, result)
        self.assertEqual(report["drawn_at_an_alias"], [])
        reception = nodes_labelled(result, RECEPTION_LABEL)
        self.assertEqual(len(reception), 1, [n["label"] for n in result.nodes])
        self.assertEqual((reception[0]["best_temporal_value"] or {}).get("best"),
                         RECEPTION_DAY)
        theirs = [node for node in result.nodes
                  if (node["best_temporal_value"] or {}).get("best")
                  == PARENTS_WEDDING_DAY]
        self.assertTrue(theirs)
        self.assertNotIn(reception[0]["node_id"], {n["node_id"] for n in theirs})

    def test_the_defect_reproduces_with_the_resolver_guard_removed(self):
        """Both legs are proved independent: put the word back inside the
        compound and `R2b` takes the pair again — and the couple key still
        refuses it, which is why the second leg is not decoration."""
        original = ident._not_a_simple_relation  # noqa: SLF001
        ident._not_a_simple_relation = lambda tokens, start, end: False  # noqa: SLF001
        try:
            views = views_of(the_three_tellings())
            self.assertEqual(views[RECEPTION_TELLING].people,
                             frozenset({"desiree", "taylor"}))
            pairs = {frozenset((link.left, link.right))
                     for link in eb.milestone_links(views)}
            self.assertIn(frozenset((RECEPTION_TELLING, AGE_TELLING)), pairs)
            # ... and never through the COUPLE bucket, at any release.
            keys = {link.key for link in eb.milestone_links(views)
                    if RECEPTION_TELLING in (link.left, link.right)}
            self.assertNotIn("married:couple:parents", keys)
        finally:
            ident._not_a_simple_relation = original  # noqa: SLF001

    def test_a_reception_that_names_a_person_reaches_the_owners_couple(self):
        """The second leg doing work of its own. Give the reception a non-owner
        person and it becomes eligible for a COUPLE bucket — and the bucket it
        lands in is the owner's, because its subject is the owner. Under the
        people-side reading it would have landed in his parents'."""
        roster = {"version": 1, "type": "person", "entities": [
            *ROSTER["entities"],
            {"name": "Katie Taylor", "slug": "katie-taylor",
             "relationship": "spouse", "aliases": ["Katie"]},
        ]}
        katie = claim(claim_type="date", subject_mention="self",
                      event_kind="moment", source=RECEPTION_RESOLVER,
                      temporal_value=value(RECEPTION_DAY),
                      event_mention="Wedding reception with Katie in "
                                    "mother-in-law's backyard",
                      quote="We had the reception in Katie's mom's backyard")
        view = views_of([katie], roster=roster)[RECEPTION_RESOLVER]
        self.assertEqual(view.people, frozenset({"katie", "taylor"}))
        self.assertTrue(view.people)
        self.assertEqual(ident.couple_key(view.subject_mentions), "couple:spouse")
        self.assertNotEqual(ident.couple_key(view.subject_mentions),
                            "couple:parents")


# ==========================================================================
# 2 — AN IDENTITY RE-KEY PUBLISHES AN ALIAS
# ==========================================================================

GRADUATION_TELLING = "conversation:msg-150f894b07bcd1f4cd55dcee"
BABYSAT_TELLING = "conversation:msg-3ffe7851ba44a24b5a06870b"
BABYSAT_RESOLVER = "resolver:0907f1e77149ddc33da60957"
GRADUATION_YEAR = "1987"
BABYSAT_SPAN = "1982-08"
BABYSAT_LABEL = "Mom babysat Kodi and Acey Nixon"


def dad_graduated() -> dict:
    """`claim:cd8e993b6bf95a5f4c80c862` — one claim, one node, subject "Dad"."""
    return claim(claim_type="date", subject_mention="Dad",
                 event_kind="graduation", source=GRADUATION_TELLING,
                 temporal_value=value(GRADUATION_YEAR),
                 event_mention="Dad graduated",
                 quote="Dad graduated in 1987")


def babysat_occurrence() -> dict:
    """`claim:1e2c40f6fdf70b32fcf2a078` — no `event_ref`, so its id is DERIVED
    from its subject and moves when the subject resolves."""
    return claim(claim_type="occurrence", subject_mention="Mom",
                 event_kind="event", source=BABYSAT_TELLING,
                 event_mention=BABYSAT_LABEL,
                 quote="Mom babysat Kodi and Acey Nixon for years")


def babysat_date(event_ref: str) -> dict:
    """`claim:762de8debbac149364d7bd1a` — the resolver's reading, carrying the
    node id the drawing had THEN frozen in its own `event_ref`."""
    return claim(claim_type="date", subject_mention="Mom",
                 event_kind="event", source=BABYSAT_RESOLVER,
                 event_ref=event_ref,
                 temporal_value=value(BABYSAT_SPAN),
                 event_mention=BABYSAT_LABEL,
                 quote="Mom babysat the Nixon kids from August 1982")


class AnIdentityReKeyIsAWayANodeIdMovesTests(unittest.TestCase):
    """`tt.AN_IDENTITY_RE_KEY_IS_A_WAY_A_NODE_ID_MOVES` and the map behind it."""

    def test_the_owners_graduation_node_moves_and_is_redirected(self):
        before = derive([dad_graduated()])
        after = derive([dad_graduated()], roster=ROSTER)
        was = before.nodes[0]["node_id"]
        now_ids = {node["node_id"] for node in after.nodes}
        self.assertNotIn(was, now_ids)
        self.assertEqual(after.node_aliases.get(was),
                         next(iter(now_ids - {was})))
        self.assertEqual([row["was_node_id"]
                          for row in findings_named(after, tt.DIAGNOSTIC_IDENTITY_SUBJECT_REKEYED)],
                         [was])

    def test_the_new_node_is_the_same_claim_at_the_same_date(self):
        before = derive([dad_graduated()])
        after = derive([dad_graduated()], roster=ROSTER)
        self.assertEqual(len(after.nodes), len(before.nodes))
        node = after.nodes[0]
        self.assertEqual(node["input_claim_refs"], before.nodes[0]["input_claim_refs"])
        self.assertEqual((node["best_temporal_value"] or {}).get("best"),
                         GRADUATION_YEAR)
        self.assertEqual(node["subject_refs"], ["person/james-taylor"])

    def test_nothing_moves_when_no_subject_resolved(self):
        result = derive([dad_graduated()])
        self.assertEqual(dict(result.node_aliases), {})
        self.assertEqual(findings_named(result, tt.DIAGNOSTIC_IDENTITY_SUBJECT_REKEYED), [])

    def test_a_claim_carrying_its_own_event_ref_never_moved(self):
        """Its id was never derived from a subject."""
        pinned = claim(claim_type="date", subject_mention="Dad",
                       event_kind="graduation", source=GRADUATION_TELLING,
                       event_ref="node:" + "a" * 24,
                       temporal_value=value(GRADUATION_YEAR),
                       event_mention="Dad graduated", quote="Dad graduated in 1987")
        self.assertEqual(tt._identity_rekeys([pinned], owner_ref=OWNER), {})  # noqa: SLF001

    def test_a_mention_that_resolved_to_itself_moves_nothing(self):
        row = dict(dad_graduated())
        row["subject_ref"] = row["subject_mention"]
        self.assertEqual(tt._identity_rekeys([row], owner_ref=OWNER), {})  # noqa: SLF001

    def test_a_former_id_two_claims_disagree_about_is_dropped_whole(self):
        """`episode_fold`'s own ruling about a contested alias: a redirect to
        one of two things is worse than none."""
        one, two = dict(dad_graduated()), dict(dad_graduated())
        one["subject_ref"] = "person/james-taylor"
        two["subject_ref"] = "person/james-rowe"
        self.assertEqual(len(tt._identity_rekeys([one], owner_ref=OWNER)), 1)  # noqa: SLF001
        self.assertEqual(tt._identity_rekeys([one, two], owner_ref=OWNER), {})  # noqa: SLF001

    def test_the_alias_is_refused_when_the_drawing_still_publishes_the_key(self):
        """v342's second disposition, unchanged: a key some claim still holds is
        not redirected at all."""
        row = dict(dad_graduated())
        row["subject_ref"] = "person/james-taylor"
        moves = tt._identity_rekeys([row], owner_ref=OWNER)  # noqa: SLF001
        was, now_id = next(iter(moves.items()))
        aliases, findings = tt._identity_rekey_aliases(  # noqa: SLF001
            [row], groups={was: {}, now_id: {}}, owner_ref=OWNER)
        self.assertEqual(aliases, {})
        self.assertEqual(findings, [])
        # ... and refused just as quietly when the target is not drawn at all.
        aliases, _ = tt._identity_rekey_aliases(  # noqa: SLF001
            [row], groups={}, owner_ref=OWNER)
        self.assertEqual(aliases, {})

    def test_the_rule_is_written_down(self):
        text = tt.AN_IDENTITY_RE_KEY_IS_A_WAY_A_NODE_ID_MOVES
        self.assertIn("derived from its subject", text)
        self.assertIn("carried onto the new one", text)


class TheDuplicateUndatedNodeTests(unittest.TestCase):
    """The other half of the same seam: the claims still holding the old id are
    carried onto the new one, so one fact is never drawn twice."""

    def setUp(self):
        # The id the drawing minted for the stay BEFORE the subject resolved —
        # which is exactly what the resolver froze into its own `event_ref`.
        before = derive([babysat_occurrence()])
        self.old_id = before.nodes[0]["node_id"]
        self.claims = [babysat_occurrence(), babysat_date(self.old_id)]

    def test_before_the_roster_it_is_one_dated_node(self):
        result = derive(self.claims)
        self.assertEqual(len(nodes_labelled(result, BABYSAT_LABEL)), 1)
        self.assertEqual((result.nodes[0]["best_temporal_value"] or {}).get("best"),
                         BABYSAT_SPAN)

    def test_the_re_key_does_not_draw_the_fact_twice(self):
        result = derive(self.claims, roster=ROSTER)
        drawn = nodes_labelled(result, BABYSAT_LABEL)
        self.assertEqual(len(drawn), 1,
                         [(n["node_id"], n["input_claim_refs"]) for n in drawn])
        self.assertEqual(sorted(drawn[0]["input_claim_refs"]),
                         sorted(row["claim_id"] for row in self.claims))

    def test_the_date_comes_along_and_the_old_id_redirects(self):
        result = derive(self.claims, roster=ROSTER)
        node = nodes_labelled(result, BABYSAT_LABEL)[0]
        self.assertEqual((node["best_temporal_value"] or {}).get("best"), BABYSAT_SPAN)
        self.assertEqual(result.node_aliases.get(self.old_id), node["node_id"])
        self.assertNotIn(self.old_id, {row["node_id"] for row in result.nodes})

    def test_the_copy_no_longer_carries_a_question_the_node_beside_it_answers(self):
        result = derive(self.claims, roster=ROSTER)
        undated = [node for node in nodes_labelled(result, BABYSAT_LABEL)
                   if not (node["best_temporal_value"] or {}).get("best")]
        self.assertEqual(undated, [])
        asked = [item for item in items_of(result, "missing_anchor")
                 if BABYSAT_LABEL in (item.get("prompt_intent") or "")]
        self.assertEqual(asked, [])


class TheReKeyLosesNoPlacementTests(unittest.TestCase):
    """The v340/v342 audit invariant, over the whole re-key rather than over a
    named node — because naming the nodes is what let the last defects through."""

    def setUp(self):
        before = derive([babysat_occurrence()])
        old_id = before.nodes[0]["node_id"]
        self.claims = the_three_tellings() + [
            dad_graduated(), babysat_occurrence(), babysat_date(old_id)]
        self.before = derive(self.claims)
        self.after = derive(self.claims, roster=ROSTER)

    def test_the_re_key_loses_no_placement_and_draws_at_no_alias(self):
        report = placement_audit(self.before, self.after)
        self.assertEqual(report["lost"], [])
        self.assertEqual(report["moved"], [])
        self.assertEqual(report["drawn_at_an_alias"], [])

    def test_the_audit_sees_the_defect_when_the_alias_is_withheld(self):
        """Proved by removing the guard: with no redirect the graduation node is
        a lost placement, which is what the hosted audit reported."""
        original = tt._identity_rekey_aliases  # noqa: SLF001
        tt._identity_rekey_aliases = lambda *a, **k: ({}, [])  # noqa: SLF001
        try:
            after = derive(self.claims, roster=ROSTER)
        finally:
            tt._identity_rekey_aliases = original  # noqa: SLF001
        self.assertTrue(placement_audit(self.before, after)["lost"])

    def test_every_alias_key_is_absent_from_the_drawing(self):
        """`episode_fold.AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES`, in
        one line, over the release that adds a fourth source of aliases."""
        drawn = {node["node_id"] for node in self.after.nodes}
        self.assertEqual(sorted(set(self.after.node_aliases) & drawn), [])

    def test_every_alias_target_is_a_node_the_drawing_publishes(self):
        drawn = {node["node_id"] for node in self.after.nodes}
        self.assertEqual(
            sorted(t for t in self.after.node_aliases.values() if t not in drawn), [])

    def test_the_reception_is_still_its_own_node_on_the_whole_vault(self):
        reception = nodes_labelled(self.after, RECEPTION_LABEL)
        self.assertEqual(len(reception), 1)
        self.assertEqual((reception[0]["best_temporal_value"] or {}).get("best"),
                         RECEPTION_DAY)

    def test_the_derivation_is_deterministic_over_input_order(self):
        reversed_claims = list(reversed(self.claims))
        again = derive(reversed_claims, roster=ROSTER)
        self.assertEqual(dict(again.node_aliases), dict(self.after.node_aliases))
        self.assertEqual([node["node_id"] for node in again.nodes],
                         [node["node_id"] for node in self.after.nodes])


# ==========================================================================
# 3 — A CARD NEVER SHOWS A NODE ID AS ITS LABEL
# ==========================================================================

DANGLING_ANCHOR = tp.derive_node_id(node_kind="event", event_kind="move",
                                    subject_refs=["self"],
                                    discriminator="a-move-nobody-kept")
CABIN_TELLING = "classification:answers-a91#aaaaaaaaaaaa"


def waiting_on_a_dangling_node() -> dict:
    """The owner's own shape: a `relative_order` claim whose anchor is a node id
    the drawing no longer has, which is what made the handle a digest."""
    return claim(claim_type="relative_order", subject_mention="self",
                 event_kind="span", source=CABIN_TELLING,
                 temporal_value={"relation": "after", "anchors": [DANGLING_ANCHOR]},
                 event_mention="the cabin summer",
                 quote="it was the summer after that")


def waiting_on_something_somebody_said() -> dict:
    """The genuine kind, kept: an anchor a person could answer about."""
    return claim(claim_type="relative_order", subject_mention="self",
                 event_kind="span", source="classification:answers-a92#bbbbbbbbbbbb",
                 temporal_value={"relation": "after",
                                 "anchors": ["701 North Williams foreclosure"]},
                 event_mention="the year we rented",
                 quote="it was the year after the foreclosure")


class ACardNeverShowsANodeIdAsItsLabelTests(unittest.TestCase):
    """`tt.A_CARD_NEVER_SHOWS_A_NODE_ID_AS_ITS_LABEL` — both seats."""

    def test_the_lint_refuses_a_sentence_carrying_any_internal_id(self):
        for prefix in ("node", "claim", "work", "episode", "edge", "membership"):
            text = f"When was {prefix}:{'0' * tc.ID_DIGEST_LENGTH}?"
            with self.subTest(prefix=prefix):
                findings = cl.lint_question(text)
                self.assertEqual([row["lint"] for row in findings],
                                 [cl.QUESTION_TEMPLATE_LEAK])
                self.assertIn("internal identifier", findings[0]["detail"])

    def test_the_lint_leaves_an_ordinary_sentence_alone(self):
        for text in ("When was 701 North Williams foreclosure?",
                     "When was Fisches House?",
                     "Do you know the year of the move to Orderville?",
                     "When was the 1987 graduation?"):
            with self.subTest(text=text):
                self.assertEqual(cl.lint_question(text), [])

    def test_the_shape_is_derived_from_the_minter_not_a_list_of_prefixes(self):
        """A digest of the wrong length is not an id, and a prefix nobody has
        minted yet is refused all the same."""
        minted = tp.derive_node_id(node_kind="event", event_kind="move",
                                   subject_refs=["self"], discriminator="x")
        self.assertTrue(cl.names_an_internal_id(minted))
        self.assertTrue(cl.names_an_internal_id(f"lane:{'a' * tc.ID_DIGEST_LENGTH}"))
        self.assertFalse(cl.names_an_internal_id("node:abc"))
        self.assertFalse(cl.names_an_internal_id("Isaiah 40:31 was his verse"))
        self.assertFalse(cl.names_an_internal_id(""))

    def test_the_rung_mints_no_card_for_a_handle_that_is_an_id(self):
        result = derive([waiting_on_a_dangling_node()])
        self.assertEqual(
            [item for item in result.work_items
             if DANGLING_ANCHOR in (item.get("prompt_intent") or "")], [])
        self.assertEqual(
            [item for item in items_of(result, "missing_anchor")
             if item.get("subject_ref", "").startswith("anchor:node")], [])

    def test_the_refusal_is_reported_with_the_nodes_that_were_waiting(self):
        result = derive([waiting_on_a_dangling_node()])
        rows = findings_named(result, tt.DIAGNOSTIC_ANCHOR_WITHOUT_A_LABEL)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["anchor"], DANGLING_ANCHOR)
        self.assertTrue(rows[0]["node_ids"])

    def test_the_node_that_was_waiting_still_carries_a_card_of_its_own(self):
        """Why dropping the anchor card loses nothing: on the head this was
        measured on, 48 of 48 dependents already had one."""
        result = derive([waiting_on_a_dangling_node()])
        waiting = findings_named(result, tt.DIAGNOSTIC_ANCHOR_WITHOUT_A_LABEL)[0]
        owned = {item.get("node_ref") for item in result.work_items}
        for node_id in waiting["node_ids"]:
            with self.subTest(node_id=node_id):
                self.assertIn(node_id, owned)

    def test_the_genuine_anchors_are_kept(self):
        result = derive([waiting_on_something_somebody_said()])
        prompts = [item["prompt_intent"] for item in items_of(result, "missing_anchor")]
        self.assertIn("When was 701 North Williams foreclosure?", prompts)

    def test_no_card_in_any_whole_vault_derivation_carries_an_id(self):
        """The invariant, over every fixture this file builds."""
        before = derive([babysat_occurrence()])
        claims = the_three_tellings() + [
            dad_graduated(), babysat_occurrence(),
            babysat_date(before.nodes[0]["node_id"]),
            waiting_on_a_dangling_node(), waiting_on_something_somebody_said()]
        for roster in ((), ROSTER):
            result = derive(claims, roster=roster)
            leaked = [item["prompt_intent"] for item in result.work_items
                      if cl.names_an_internal_id(item.get("prompt_intent"))]
            with self.subTest(roster=bool(roster)):
                self.assertEqual(leaked, [])

    def test_the_rule_is_written_down(self):
        text = tt.A_CARD_NEVER_SHOWS_A_NODE_ID_AS_ITS_LABEL
        self.assertIn("no human label", text)
        self.assertIn("digest", text)


class TheAnchorSentenceIsGrammarTests(unittest.TestCase):
    """v343's `_is_gerund_phrase` has a mirror: a phrase that LEADS with a verb
    is a bare predicate, whatever its length."""

    def test_the_owners_two_phrases_are_asked_the_same_way(self):
        for body in ("left Kristen", "moved in with dad"):
            with self.subTest(body=body):
                self.assertEqual(tt.compose_anchor_question(body),
                                 f"You mentioned {body} — when was that?")

    def test_a_word_count_no_longer_decides_it(self):
        self.assertTrue(tt._leads_with_a_verb("left Kristen"))  # noqa: SLF001
        self.assertTrue(tt._leads_with_a_verb("moved in with dad"))  # noqa: SLF001
        self.assertTrue(tt._leads_with_a_verb("graduated from BYU"))  # noqa: SLF001

    def test_an_event_noun_is_still_a_noun(self):
        """One vocabulary with `_is_gerund_phrase`: `_ING_EVENT_NOUNS`."""
        for body in ("wedding reception", "meeting with Sam", "morning walk"):
            with self.subTest(body=body):
                self.assertFalse(tt._leads_with_a_verb(body))  # noqa: SLF001

    def test_a_name_or_a_place_is_no_predicate(self):
        for body in ("Fisches House", "Beauchamps residence",
                     "701 North Williams foreclosure", "Dad's death"):
            with self.subTest(body=body):
                self.assertFalse(tt._leads_with_a_verb(body))  # noqa: SLF001
                self.assertEqual(tt.compose_anchor_question(body),
                                 f"When was {body}?")

    def test_a_single_word_is_not_a_clause(self):
        self.assertFalse(tt._leads_with_a_verb("left"))  # noqa: SLF001
        self.assertEqual(tt.compose_anchor_question("Fisches House"),
                         "When was Fisches House?")

    def test_the_noun_first_shape_still_asks_whose(self):
        """v343's own sentence for an event with nobody in it is untouched."""
        self.assertEqual(
            tt.compose_anchor_question("move to Orderville"),
            "You mentioned the move to Orderville — whose move was that, and when?")


# ==========================================================================
# The version
# ==========================================================================


class CalculationRuleVersionTests(unittest.TestCase):

    def test_the_rule_version_moved(self):
        """Nodes, aliases AND cards change for a vault nobody edited, which is
        what this number is for."""
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:18")
        result = derive([dad_graduated()], roster=ROSTER)
        for node in result.nodes:
            self.assertEqual(node["calculation_rule_version"], "timeline-rules:18")

    def test_the_three_rules_are_reachable_by_name(self):
        for module, name in ((eb, "A_COUPLE_IS_TWO_PEOPLE"),
                             (tt, "AN_IDENTITY_RE_KEY_IS_A_WAY_A_NODE_ID_MOVES"),
                             (tt, "A_CARD_NEVER_SHOWS_A_NODE_ID_AS_ITS_LABEL")):
            with self.subTest(name=name):
                self.assertTrue(getattr(module, name))

    def test_the_dates_still_agree_helper_is_the_shared_one(self):
        """`placement_audit` is v345's, imported rather than copied."""
        self.assertTrue(chrono.dates_agree(chrono.from_dict(value("1987")),
                                           chrono.from_dict(value("1987"))))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
