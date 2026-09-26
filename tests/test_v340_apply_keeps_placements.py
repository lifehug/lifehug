"""v340 — a binder apply never loses a placement or moves a dated moment.

The incident, measured on a scratch clone of the owner's vault at
`e4add76d` with v339 bytes (`bind-episodes --apply` filed 533 envelopes and
140 proposals, then a publish took generation 147 to 148):

* placed nodes 1183 → 1111, open cards 50 → 81 (precision gap 43 → 70);
* 482 of the "lost" placements were only RE-KEYED — the old node id is in
  ``node_aliases`` and the target carries the same date, which is Law 5
  working;
* **36 were really lost, and every one of them had been placed with
  ``basis: "age"``** ("Went bankrupt at 26" 2007~, "Served two-year Mormon
  mission" 2000~, "Started first job at AJ's Pizza" 1996~, "Marriage to
  Katie", "College graduation", "Move to Seattle"…). The projection's own
  ``age_without_birth_anchor`` finding went 18 → 59 and
  ``age_frames_ambiguous_birth`` appeared for the first time: the owner's age
  ANCHOR had gone, so the arithmetic had nothing to measure from and every
  age placement fell to unplaced without a word;
* and one merge was flatly wrong: "Family moved to Yucaipa" (the childhood
  move, placed 1981-07-11/1982-07) was aliased INTO a "Family moved to
  Yucaipa" dated 2013-06/.. — two different moves, one label, 32 years apart.

Both halves are guarded here. Every negative below was run against a build
with its guard removed and SEEN failing first.
"""

from __future__ import annotations

import collections
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_binder as eb  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-23T12:00:00Z"


# --------------------------------------------------------------------------
# Claims, in the shapes the two live extractors actually file
# --------------------------------------------------------------------------


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    source = overrides.pop("source")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence somebody said")}],
        "extractor_version": "classifier:1",
        "created_at": "2026-01-01T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def node_of(discriminator: str, *, subject: str = "self") -> str:
    return tp.derive_node_id(node_kind="event", event_kind="moment",
                             subject_refs=[subject], discriminator=discriminator)


def index_of(claims) -> dict:
    return {"version": ts.INDEX_VERSION, "claims": list(claims)}


def derive(claims, *, episode_records=()) -> object:
    return tt.derive_calculated_timeline(
        index_of(claims), episode_records=episode_records, now=NOW
    )


def findings(result) -> dict:
    return dict(collections.Counter(
        row.get("finding") for row in result.diagnostics.get("findings") or ()
    ))


def node_named(result, label: str) -> dict:
    rows = [node for node in result.nodes if node.get("label") == label]
    assert len(rows) == 1, f"{label!r} names {len(rows)} nodes"
    return rows[0]


def best_of(node: dict) -> tuple:
    row = node.get("best_temporal_value") or {}
    return row.get("best"), row.get("basis")


def write_vault(root: Path, claims) -> None:
    """The claims on disk as the receipts a vault actually holds."""
    (root / "state" / "temporal_claims").mkdir(parents=True, exist_ok=True)
    by_source: dict[str, list] = {}
    for row in claims:
        by_source.setdefault(row["source_ref"]["source_id"], []).append(row)
    for source_id in sorted(by_source):
        batch = by_source[source_id]
        ts.write_receipt(root, {"source_ref": batch[0]["source_ref"],
                                "extractor_version": batch[0]["extractor_version"],
                                "created_at": batch[0]["created_at"],
                                "claims": batch}, now=NOW)
    ts.rebuild_active_index(root)


# --------------------------------------------------------------------------
# The vault the age half is measured on — the incident's own shape
# --------------------------------------------------------------------------

BANKRUPT_NODE = node_of("bankrupt")
SON_BIRTHDAY_TELLING = "classification:sources-birthdays#aaaaaaaaaaaa"
SON_TURNING_TELLING = "classification:answers-q3#bbbbbbbbbbbb"


def owner_birth() -> dict:
    """The owner's birthday, in the spelling his vault files it in: the LANDMARK
    domain word as the subject mention, which the fold resolves to him."""
    return claim(claim_type="date", subject_mention="birth", event_kind="birth",
                 source="landmark:entry-birth", temporal_value=value("1981-07-11"),
                 quote="I was born on 11 July 1981.")


def owner_age() -> dict:
    return claim(claim_type="age", subject_mention="self", event_kind="moment",
                 source="classification:answers-a1#cccccccccccc",
                 event_ref=BANKRUPT_NODE, temporal_value="26",
                 event_mention="Went bankrupt at 26", quote="I went bankrupt at 26.")


def sons_birth_tellings() -> list:
    """Two tellings of the SON's birth — and the second one's subject is the
    OWNER, because he is the subject of the turning point and the birth is only
    what turned it. This is the exact pair the owner's vault carries for
    Harvey ("Harvey's birth as turning point", `subject_mention: "self"`)."""
    return [
        claim(claim_type="date", subject_mention="Wren Ashgrove", event_kind="birth",
              source=SON_BIRTHDAY_TELLING, temporal_value=value("2021-10-11"),
              event_mention="Wren Ashgrove's birth",
              quote="Wren Ashgrove. Born 11 October 2021."),
        claim(claim_type="occurrence", subject_mention="self", event_kind="moment",
              source=SON_TURNING_TELLING, event_mention="Wren's birth as turning point",
              quote="Wren's birth was the turning point for me."),
        claim(claim_type="occurrence", subject_mention="Wren Ashgrove",
              event_kind="moment", source=SON_TURNING_TELLING,
              event_mention="Wren's birth as turning point",
              quote="Wren's birth was the turning point for me."),
    ]


def age_vault_claims() -> list:
    return [owner_birth(), owner_age(), *sons_birth_tellings()]


def the_bind(claims) -> dict:
    """The binder envelope that folds the son's two birth tellings into one
    episode — `R2b`, one subject's one birth — as `episode_records`."""
    views = eb.telling_views(claims)
    members = tuple(sorted((SON_BIRTHDAY_TELLING, SON_TURNING_TELLING)))
    envelope = eb.group_envelope(
        {"members": members, "tellings": members,
         "rule_ids": (eb.RULE_ID_MILESTONE,), "reasons": ()},
        views=views, active={}, now=NOW,
    )
    return {"operations": [envelope["operation"]], "bindings": envelope["bindings"]}


class TheAgeAnchorSurvivesABindTests(unittest.TestCase):
    """The 36 lost placements, at the seam that lost them."""

    def setUp(self):
        self.claims = age_vault_claims()
        self.before = derive(self.claims)
        self.after = derive(self.claims, episode_records=the_bind(self.claims))

    # -- the incident, reproduced ----------------------------------------

    def test_the_bind_mints_a_second_node_that_reads_as_the_owners_birth(self):
        """The mechanism: one episode over the son's two birth tellings means
        one node; its kind is the strongest anybody gave it (`birth`) and its
        resolved subject is the owner (from the turning-point claims). So a
        vault with ONE birthday on file now holds two groups that answer to
        "the owner's birth", one of them at his son's birthday."""
        titles = [node["label"] for node in self.after.nodes
                  if node.get("event_kind") == "birth"]
        # v360 (owner, 2026-09-25): a title is sentence-cased now.
        self.assertEqual(titles.count("Your birth"), 2)
        son = [node for node in self.after.nodes
               if node.get("event_kind") == "birth"
               and "Wren Ashgrove" in (node.get("subject_refs") or ())]
        self.assertEqual(len(son), 1)
        self.assertIn("self", son[0]["subject_refs"])
        self.assertEqual(best_of(son[0]), ("2021-10-11", "stated"))

    # -- the fix ----------------------------------------------------------

    def test_the_age_placement_still_stands(self):
        """The whole point. "Went bankrupt at 26" is dated by the owner's
        birthday, and a bind that re-keys a birth telling may not cost him
        that date."""
        self.assertEqual(best_of(node_named(self.before, "Went bankrupt at 26")),
                         ("2007~", "age"))
        self.assertEqual(best_of(node_named(self.after, "Went bankrupt at 26")),
                         ("2007~", "age"))

    def test_the_owners_own_birthday_is_untouched(self):
        for result in (self.before, self.after):
            owner = [node for node in result.nodes
                     if node.get("event_kind") == "birth"
                     and node.get("subject_refs") == ["self"]]
            self.assertEqual(len(owner), 1)
            self.assertEqual(best_of(owner[0]), ("1981-07-11", "stated"))

    def test_the_age_frames_still_stand(self):
        """`_owner_birth` is the frames' origin and it refused on the same
        arithmetic, so the incident cost the owner every age frame too."""
        def frames(result):
            return [node["label"] for node in result.nodes
                    if node.get("event_kind") == "age_frame"]
        self.assertEqual(frames(self.after), frames(self.before))
        self.assertGreaterEqual(len(frames(self.after)), 4)

    def test_nothing_says_the_anchor_was_missing(self):
        self.assertNotIn("age_without_birth_anchor", findings(self.after))
        self.assertNotIn("age_frames_ambiguous_birth", findings(self.after))
        self.assertNotIn("owner_birth_anchor_ambiguous", findings(self.after))

    # -- the negative: the guard removed ---------------------------------

    def test_without_the_narrowing_the_placement_and_the_frames_are_lost(self):
        """v339's rule, restored for one call: every birth group that reads as
        the owner's, un-narrowed. Two of them, so `len(births) == 1` fails and
        the anchor falls to `None` — and this is the run that was measured on
        the clone, findings and all."""
        original = tt._owner_birth_readings

        def v339(groups, owner, *, reads_as_owner):
            return [(node_id, group) for node_id, group in sorted(groups.items())
                    if tt.collapsed_text(group.get("event_kind")) == "birth"
                    and reads_as_owner(group)]

        tt._owner_birth_readings = v339
        try:
            lost = derive(self.claims, episode_records=the_bind(self.claims))
        finally:
            tt._owner_birth_readings = original
        self.assertEqual(best_of(node_named(lost, "Went bankrupt at 26")), (None, None))
        self.assertEqual(
            [node for node in lost.nodes if node.get("event_kind") == "age_frame"], [])
        self.assertIn("age_without_birth_anchor", findings(lost))
        self.assertIn("age_frames_ambiguous_birth", findings(lost))

    def test_an_ambiguous_reading_is_refused_out_loud(self):
        """The narrowing is not a licence to pick. A vault that really does hold
        two birthdays for the owner ALONE still refuses — that is v339's own
        ruling and it stands — but it now says which two nodes it could not
        choose between, so the loss is never silent again."""
        second = claim(claim_type="date", subject_mention="self", event_kind="birth",
                       source="classification:answers-a9#dddddddddddd",
                       event_ref=node_of("other-birth"),
                       temporal_value=value("1982-03-04"),
                       quote="Actually I think it was 4 March 1982.")
        result = derive([*self.claims, second])
        self.assertEqual(best_of(node_named(result, "Went bankrupt at 26")), (None, None))
        found = findings(result)
        self.assertIn("owner_birth_anchor_ambiguous", found)
        self.assertIn("age_without_birth_anchor", found)

    def test_a_birth_that_names_somebody_else_is_never_the_owners_anchor(self):
        """:data:`temporal_timeline.OWNER_BIRTH_IS_ABOUT_NOBODY_ELSE`, as a unit."""
        owner_only = {"claims": [
            {"subject_mention": "birth", "event_kind": "birth", "subject_ref": "self"},
            {"subject_mention": "self", "event_kind": "birth", "subject_ref": None},
        ]}
        also_the_son = {"claims": [
            {"subject_mention": "self", "event_kind": "moment", "subject_ref": None},
            {"subject_mention": "Wren", "event_kind": "birth",
             "subject_ref": "person/wren"},
        ]}
        self.assertTrue(tt._birth_names_only_the_owner(owner_only, "self"))
        self.assertFalse(tt._birth_names_only_the_owner(also_the_son, "self"))


# --------------------------------------------------------------------------
# The Yucaipa half — a merge never moves a dated moment
# --------------------------------------------------------------------------

CHILDHOOD_NODE = node_of("yucaipa-childhood")
LATER_NODE = node_of("yucaipa-2013")


def move_telling(source: str, node: str, label: str, *, dated: str | None = None,
                 people=("Nan Beauchamp",)) -> list:
    """One telling of one move: the owner's own claim, plus a claim per other
    person it names, which is what makes the cast agree rather than the words."""
    rows = [claim(
        claim_type=("date" if dated else "occurrence"), subject_mention="self",
        event_kind="moment", event_ref=node, event_mention=label,
        source=source, quote=label,
        **({"temporal_value": value(dated)} if dated else {}),
    )]
    for person in people:
        rows.append(claim(claim_type="occurrence", subject_mention=person,
                          event_kind="moment", event_ref=node, event_mention=label,
                          source=source, quote=label))
    return rows


SAME_LABEL = "Family moved to Yucaipa"
CHILDHOOD_DATED = "classification:answers-a1#111111111111"
CHILDHOOD_RETOLD = "classification:answers-a2#222222222222"
LATER_DATED = "classification:answers-a3#333333333333"
LATER_RETOLD = "classification:answers-a4#444444444444"


def yucaipa_claims(*, childhood_label=SAME_LABEL, later_label=SAME_LABEL,
                   retold_childhood=None, retold_later=None) -> list:
    """Four tellings of two different moves, and the shape is the incident's.

    Each move has one DATED telling and one retelling that states no date of its
    own. The retellings are the tellings that mattered: the projection places
    them — they are claims of the same node as their dated sibling — but their
    own claims say nothing about when, so v339's :func:`episode_binder._bounds_of`
    read both of them as undated and `R2c` bound the 1981 move to the 2013 one.
    """
    return [
        *move_telling(CHILDHOOD_DATED, CHILDHOOD_NODE, childhood_label,
                      dated="1981-07-11"),
        *move_telling(CHILDHOOD_RETOLD, CHILDHOOD_NODE,
                      retold_childhood or childhood_label),
        *move_telling(LATER_DATED, LATER_NODE, later_label, dated="2013-06-01"),
        *move_telling(LATER_RETOLD, LATER_NODE, retold_later or later_label),
    ]


def views_for(claims, *, placed: bool) -> dict:
    windows = eb.fold_placed_windows(claims) if placed else None
    return eb.telling_views(claims, placed_windows=windows)


def crossing(links) -> list:
    """Every link that joins the childhood move to the later one."""
    childhood = {CHILDHOOD_DATED, CHILDHOOD_RETOLD}
    later = {LATER_DATED, LATER_RETOLD}
    return sorted(
        link.members for link in links
        if (link.left in childhood and link.right in later)
        or (link.left in later and link.right in childhood)
    )


class AMergeNeverMovesADatedMomentTests(unittest.TestCase):
    """:data:`episode_binder.A_MERGE_NEVER_MOVES_A_DATED_MOMENT`."""

    def test_the_placed_window_is_the_folds_own_answer(self):
        """Not a second reading of the dates: each telling's window is the
        ``best_temporal_value`` of the node the FOLD put its claims in, which is
        why a retelling that states nothing still has one."""
        claims = yucaipa_claims()
        windows = eb.fold_placed_windows(claims)
        self.assertEqual(windows[CHILDHOOD_DATED].best, "1981-07-11")
        self.assertEqual(windows[CHILDHOOD_RETOLD].best, "1981-07-11")
        self.assertEqual(windows[LATER_DATED].best, "2013-06-01")
        self.assertEqual(windows[LATER_RETOLD].best, "2013-06-01")
        views = views_for(claims, placed=True)
        self.assertIsNone(views[CHILDHOOD_RETOLD].bounds)
        self.assertEqual(views[CHILDHOOD_RETOLD].placed_bounds.best, "1981-07-11")
        self.assertTrue(views[CHILDHOOD_RETOLD].as_dict()["placed"])

    def test_r2c_refuses_the_two_yucaipa_moves(self):
        claims = yucaipa_claims()
        links = eb.same_label_links(views_for(claims, placed=True))
        self.assertEqual(crossing(links), [])
        # …and still says the two retellings of ONE move are that move.
        self.assertIn((CHILDHOOD_DATED, CHILDHOOD_RETOLD),
                      [link.members for link in links])

    def test_without_the_placed_windows_r2c_bound_them(self):
        """The negative, which is the incident: three of v339's five links cross
        the 32 years, and the group they make moves the childhood move to 2013."""
        links = eb.same_label_links(views_for(yucaipa_claims(), placed=False))
        self.assertEqual(
            crossing(links),
            [(CHILDHOOD_DATED, LATER_RETOLD), (CHILDHOOD_RETOLD, LATER_DATED),
             (CHILDHOOD_RETOLD, LATER_RETOLD)],
        )

    def test_r2d_refuses_the_same_contradiction(self):
        claims = yucaipa_claims(
            childhood_label="Beauchamp house move with Nan",
            retold_childhood="Nan Beauchamp house move recalled",
            later_label="Beauchamp house move to Yucaipa",
            retold_later="Nan Beauchamp house move written down",
        )
        self.assertEqual(crossing(eb.restatement_links(views_for(claims, placed=True))), [])
        self.assertEqual(
            crossing(eb.restatement_links(views_for(claims, placed=False))),
            [(CHILDHOOD_DATED, LATER_RETOLD), (CHILDHOOD_RETOLD, LATER_DATED),
             (CHILDHOOD_RETOLD, LATER_RETOLD)],
        )

    def test_a_telling_the_fold_has_not_placed_still_binds(self):
        """The rungs exist FOR the unplaced retelling, so an unplaced side
        agrees with everything — the refusal is about contradiction, never
        about caution."""
        claims = [
            *move_telling(CHILDHOOD_DATED, CHILDHOOD_NODE, SAME_LABEL,
                          dated="1981-07-11"),
            *move_telling(LATER_RETOLD, node_of("orphan"), SAME_LABEL),
        ]
        links = eb.same_label_links(views_for(claims, placed=True))
        self.assertEqual([link.members for link in links],
                         [(CHILDHOOD_DATED, LATER_RETOLD)])

    def test_two_placements_that_overlap_still_bind(self):
        claims = [
            *move_telling(CHILDHOOD_DATED, CHILDHOOD_NODE, SAME_LABEL, dated="1981-07-11"),
            *move_telling(CHILDHOOD_RETOLD, CHILDHOOD_NODE, SAME_LABEL),
            *move_telling(LATER_DATED, LATER_NODE, SAME_LABEL, dated="1981-07-11"),
            *move_telling(LATER_RETOLD, LATER_NODE, SAME_LABEL),
        ]
        self.assertNotEqual(crossing(eb.same_label_links(views_for(claims, placed=True))), [])

    def test_the_stated_dates_are_still_refused_on_their_own(self):
        """v333's half of the rule, untouched: two tellings that STATE
        contradicting dates never needed a projection to be refused."""
        views = views_for(yucaipa_claims(), placed=True)
        self.assertFalse(eb._dates_agree(views[CHILDHOOD_DATED].bounds,
                                        views[LATER_DATED].bounds))
        self.assertTrue(eb._dates_agree(views[CHILDHOOD_DATED].bounds, None))

    def test_the_rung_ids_the_rule_governs_are_the_word_rungs(self):
        """`R2a` and `R2b` are deliberately NOT governed: their key is the
        identity of one fact, and two readings of one fact that disagree about
        its date are the contradiction a fold exists to surface — which is how
        the vault's duplicate births fold at all."""
        claims = yucaipa_claims()
        views = views_for(claims, placed=True)
        self.assertEqual(eb.milestone_links(views), [])
        self.assertEqual(
            {link.rule_id for link in eb.exact_identity_links(views)},
            {eb.RULE_ID_SAME_LABEL},
        )


# --------------------------------------------------------------------------
# On a vault, through the real verbs
# --------------------------------------------------------------------------


class OnAVaultTests(unittest.TestCase):
    """`bind-episodes --apply` then `publish`, on disk, through no other door."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="v340-")
        write_vault(self.root, [*yucaipa_claims(), owner_birth(), owner_age()])

    def publish(self) -> dict:
        pub.publish(self.root, roster_snapshot=(), now=NOW, full=True)
        return pub.read_projection(self.root) or {}

    def placements(self, projection: dict) -> dict:
        found: dict[str, set] = {}
        for node in projection.get("nodes") or ():
            row = node.get("best_temporal_value") or {}
            if row.get("best"):
                found.setdefault(node["label"], set()).add(row["best"])
        return found

    def test_the_apply_keeps_both_moves_and_the_age_placement(self):
        before = self.publish()
        self.assertEqual(self.placements(before)[SAME_LABEL],
                         {"1981-07-11", "2013-06-01"})
        outcome = eb.bind_episodes(self.root, apply=True, now=NOW)
        after = self.publish()
        # The two moves are still two moves, each still on its own date.
        self.assertEqual(self.placements(after)[SAME_LABEL],
                         {"1981-07-11", "2013-06-01"})
        self.assertEqual(self.placements(after)["Went bankrupt at 26"], {"2007~"})
        # Nothing the apply filed joins a 1981 telling to a 2013 one.
        for group in outcome["plan"].exact_groups:
            members = set(group["members"])
            self.assertFalse(
                members & {CHILDHOOD_DATED, CHILDHOOD_RETOLD}
                and members & {LATER_DATED, LATER_RETOLD},
                f"{group['rule_ids']} moved a dated moment: {sorted(members)}",
            )
        # And a placement count never falls across an apply.
        self.assertGreaterEqual(len(self.placements(after)),
                                len(self.placements(before)))

    def test_the_plan_reads_the_folds_placements(self):
        inputs = eb.read_vault_inputs(self.root, now=NOW)
        self.assertEqual(inputs["placed_windows"][CHILDHOOD_RETOLD].best, "1981-07-11")
        self.assertEqual(inputs["placed_windows"][LATER_RETOLD].best, "2013-06-01")
        # One derivation, read twice.
        self.assertTrue(inputs["frames"])

    def test_a_replay_is_still_a_no_op(self):
        eb.bind_episodes(self.root, apply=True, now=NOW)
        second = eb.bind_episodes(self.root, apply=True, now="2027-01-01T00:00:00Z")
        self.assertEqual(second["plan"].exact_groups, [])


class PlacementsComeFromThePublishedGenerationTests(unittest.TestCase):
    """:data:`episode_binder.PLACEMENTS_COME_FROM_THE_PUBLISHED_GENERATION`.

    The Yucaipa placements are `basis: "anchor", confidence: "inferred"` with no
    provenance of their own — computed from containment inside a residence stay,
    which the binder's one-argument derivation cannot see. So the guard reads
    the PUBLISHED generation, and this is that difference, measured.
    """

    def setUp(self):
        self.claims = [
            *move_telling(CHILDHOOD_RETOLD, node_of("childhood-only"), SAME_LABEL),
            *move_telling(LATER_RETOLD, node_of("later-only"), SAME_LABEL),
        ]

    def inferred(self, telling: str, best: str, latest: str) -> dict:
        """One published node, in the shape the incident's own nodes carry."""
        return {
            "node_id": f"node:{telling[-12:]}",
            "input_claim_refs": [row["claim_id"] for row in self.claims
                                 if row["source_ref"]["source_id"] == telling],
            "best_temporal_value": {"best": best, "earliest": best.split("/")[0],
                                    "latest": latest, "granularity": "range",
                                    "basis": "anchor", "confidence": "inferred",
                                    "anchors": [], "provenance": []},
        }

    def test_the_bare_fold_cannot_see_these_placements(self):
        self.assertEqual(eb.fold_placed_windows(self.claims), {})
        self.assertEqual(
            crossing(eb.same_label_links(eb.telling_views(self.claims))),
            [(CHILDHOOD_RETOLD, LATER_RETOLD)],
        )

    def test_the_published_generation_does_and_the_merge_is_refused(self):
        nodes = [self.inferred(CHILDHOOD_RETOLD, "1981-07-11/1982-07", "1982-07"),
                 self.inferred(LATER_RETOLD, "2013-06/..", None)]
        windows = eb.placed_windows_of(nodes, self.claims)
        self.assertEqual(windows[CHILDHOOD_RETOLD].best, "1981-07-11/1982-07")
        self.assertEqual(windows[LATER_RETOLD].best, "2013-06/..")
        views = eb.telling_views(self.claims, placed_windows=windows)
        self.assertEqual(crossing(eb.same_label_links(views)), [])

    def test_a_vault_read_merges_the_two_and_the_projection_wins(self):
        root = root_parent_tmp(self, ROOT, prefix="v340-published-")
        write_vault(root, [*yucaipa_claims(), owner_birth(), owner_age()])
        pub.publish(root, roster_snapshot=(), now=NOW, full=True)
        inputs = eb.read_vault_inputs(root, now=NOW)
        self.assertEqual(inputs["placed_windows"][CHILDHOOD_RETOLD].best, "1981-07-11")
        self.assertEqual(inputs["placed_windows"][LATER_RETOLD].best, "2013-06-01")


class DeterminismTests(unittest.TestCase):
    def test_the_placed_windows_are_a_pure_function_of_the_claims(self):
        import random

        claims = yucaipa_claims()
        shuffled = list(claims)
        random.Random(340).shuffle(shuffled)
        left = {key: record.to_dict()
                for key, record in eb.fold_placed_windows(claims).items()}
        right = {key: record.to_dict()
                 for key, record in eb.fold_placed_windows(shuffled).items()}
        self.assertEqual(left, right)

    def test_a_window_is_a_chronology_record(self):
        for record in eb.fold_placed_windows(yucaipa_claims()).values():
            self.assertIsInstance(record, chrono.DateRecord)


if __name__ == "__main__":
    unittest.main()
