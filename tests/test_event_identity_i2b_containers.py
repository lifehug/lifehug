"""Event identity I2b — containers first: the entity signal and the containment rung.

Controlling design: lifehug-platform `docs/design/event-identity.md` **v4.2**,
amendment §12b (rulings 1, 2, 5, 6, 7) and the §13.5 promises. I0–I3 built
SAMENESS; the first real-vault dry run bound nothing, and the owner read that
as an emphasis error — *"we're trying to collect things into events so they can
be visualized"*. This phase is the collecting half, and these are its promises
as tests.

The fixture is a small synthetic life with the SHAPES the founder's vault
actually holds: a recorder telling whose subject IS the thing ("Etherfuse",
started, 2022-05), classifier tellings that name it only inside a sentence
("Started Etherfuse", undated), a closed span ("Joy Labs", 2018-11→2021-01), a
point-dated birth that must NOT become a container, and a roster that
recognizes two of those names and not the third. Every name, date and word is
synthetic; NOTHING here reads ~/Workspace/dave.

Every negative below was run against a build with its guard removed and SEEN
failing first; the evidence table is in the PR body.
"""

from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-31T12:00:00Z"


# --------------------------------------------------------------------------
# The fixture — the founder's SHAPES, none of the founder's life
# --------------------------------------------------------------------------

#: Two rosters, and deliberately a third name in neither: `Northgate` is what
#: proves the entity signal is the ROSTER's recognition rather than the string.
ROSTERS = {
    "person": {"type": "person", "entities": [
        {"name": "Wren Alder", "slug": "wren-alder",
         "aliases": ["Wren", "Wren A."]},
    ]},
    "place": {"type": "place", "entities": [
        {"name": "Cedarport", "slug": "cedarport", "aliases": []},
    ]},
    "theme": {"type": "theme", "entities": [
        {"name": "Halcyon", "slug": "halcyon",
         "aliases": ["Halcyon Works", "the Halcyon thesis"]},
        {"name": "Tidewheel", "slug": "tidewheel", "aliases": []},
        # Three letters: a key this short is not a name, and the floor
        # (`ENTITY_KEY_MIN_CHARS`) is what keeps it from collecting a life.
        {"name": "Ash", "slug": "ash", "aliases": []},
    ]},
}


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def value(text: str, *, basis: str = "stated") -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": basis, "confidence": "certain"}


def claim(*, source: str, **overrides) -> dict:
    """One claim, keyed so its telling ref IS its source id (C1's own rule).

    A classifier telling carries its own ``event_ref`` because that is what the
    classifier files: without one, every `moment` claim about the same subject
    would collapse into ONE node and the fold would have nothing separate to
    hang a containment on.
    """
    if overrides.get("event_mention") and "event_ref" not in overrides:
        overrides["event_ref"] = tp.derive_node_id(
            node_kind="event", event_kind=overrides.get("event_kind") or "moment",
            subject_refs=["I"], discriminator=source,
        )
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence somebody said")}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": "occurrence",
        "subject_mention": "I",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


#: The recorder's shape: the subject IS the thing, and a `started` claim opens
#: the span. This is the row the founder's own work entry has.
HALCYON = "landmark:entry-halcyon"
HALCYON_END = "landmark:entry-tidewheel"
IDEA = "conversation:msg-halcyon-idea"
BIRTH = "landmark:entry-birth"


def base_claims() -> list:
    return [
        # The owner's birthday, the shape the fold resolves to the owner.
        claim(source=BIRTH, claim_type="date", subject_mention="birth",
              event_kind="birth", temporal_value=value("1981-07-11"),
              quote="I was born on 11 July 1981."),
        # A CONTAINER: subject is the thing, `started` opens an open-ended span.
        claim(source=HALCYON, claim_type="date", subject_mention="Halcyon",
              event_kind="started", temporal_value=value("2022-05"),
              quote="Halcyon, May 2022 - Present"),
        # A CLOSED container: started and ended.
        claim(source=HALCYON_END, claim_type="date", subject_mention="Tidewheel",
              event_kind="started", temporal_value=value("2018-11"),
              quote="Tidewheel started in November 2018"),
        claim(source=HALCYON_END, claim_type="date", subject_mention="Tidewheel",
              event_kind="ended", temporal_value=value("2021-01"),
              quote="Tidewheel ended in January 2021"),
        # A container the person dated differently — the second Halcyon frame.
        claim(source=IDEA, claim_type="date", subject_mention="the idea for Halcyon",
              event_kind="started", temporal_value=value("2021"),
              quote="The idea for Halcyon was 2021"),
        # A MEMBER: names the entity only inside a sentence, and is undated.
        claim(source="classification:answers-a1#aaa1", event_mention="Started Halcyon",
              event_kind="moment", quote="We started Halcyon in a garage."),
        # A member dated INSIDE the open span.
        claim(source="classification:answers-a2#aaa2", claim_type="date",
              event_mention="Halcyon's first customer", event_kind="moment",
              temporal_value=value("2023-04"), quote="Halcyon's first customer."),
        # A member dated OUTSIDE every Halcyon span — must not be placed.
        claim(source="classification:answers-a3#aaa3", claim_type="date",
              event_mention="Halcyon was only a daydream then", event_kind="moment",
              temporal_value=value("1999"), quote="Halcyon was only a daydream."),
        # A telling naming a word NO roster knows — no entity, no containment.
        claim(source="classification:answers-a4#aaa4", event_mention="Northgate opened",
              event_kind="moment", quote="Northgate opened that spring."),
        # A telling naming the three-letter theme — below the name floor.
        claim(source="classification:answers-a5#aaa5", event_mention="Ash everywhere",
              event_kind="moment", quote="Ash everywhere."),
        # A point-dated moment that is NOT a container even though its subject
        # resolves: a birth is a moment, not a stretch.
        claim(source="landmark:entry-wren", claim_type="date",
              subject_mention="Wren Alder", event_kind="birth",
              temporal_value=value("2010-12-21"), quote="Wren Alder, born 2010-12-21"),
    ]


def index_of(claims=None):
    return ec.entity_index(ROSTERS), (claims if claims is not None else base_claims())


def views_for(claims=None, *, entity_index=None):
    rosters, rows = index_of(claims)
    return eb.telling_views(rows, entity_index=entity_index or rosters)


def plan_for(claims=None, **kwargs):
    rosters, rows = index_of(claims)
    kwargs.setdefault("entity_index", rosters)
    kwargs.setdefault("now", NOW)
    return eb.plan(rows, **kwargs)


def container_named(result, label):
    for container in result.containers.values():
        if container.label == label:
            return container
    raise AssertionError(f"no container labelled {label!r}: "
                         f"{[c.label for c in result.containers.values()]}")


def members_of(result, label):
    container = container_named(result, label)
    for block in result.containments:
        if block["episode_id"] == container.episode_id:
            return {row["telling_ref"]: row for row in block["members"]}
    return {}


def seed_vault(root: Path, claims) -> None:
    by_source: dict = {}
    for row in claims:
        key = (row["source_ref"]["source_id"], row["source_ref"]["revision"],
               row["extractor_version"])
        by_source.setdefault(key, []).append(row)
    for (_source_id, _revision, extractor), rows in sorted(by_source.items()):
        ts.write_receipt(root, {
            "source_ref": rows[0]["source_ref"],
            "extractor_version": extractor,
            "created_at": "2026-08-30T00:00:00Z",
            "claims": [dict(row) for row in rows],
        })
    ts.rebuild_active_index(root)


def seed_rosters(root: Path) -> None:
    import json

    directory = root / "state" / "entity_rosters"
    directory.mkdir(parents=True, exist_ok=True)
    for kind, snapshot in ROSTERS.items():
        (directory / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")


# ==========================================================================
# §12b ruling 1 — the entity signal
# ==========================================================================


class EntitySignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index, self.claims = index_of()
        self.views = views_for()

    def test_it_is_one_signal_in_retrieval_and_in_condition_four(self):
        """§13.5: *a roster-resolved same entity counts as exactly one
        independent signal, in retrieval and in R1's condition 4*."""
        self.assertIn(ec.ENTITY_SIGNAL, eb.RETRIEVAL_SIGNALS)
        self.assertIn(ec.ENTITY_SIGNAL, eb.INDEPENDENT_SIGNALS)
        units = eb.candidates(self.views)
        view = self.views["classification:answers-a1#aaa1"]
        candidate = units[HALCYON]
        self.assertIn(ec.ENTITY_SIGNAL, eb.retrieval_signals(view, candidate))
        found = eb.independent_signals(view, candidate)
        self.assertEqual(found.count(ec.ENTITY_SIGNAL), 1)

    def test_the_recognition_is_the_evidence_not_the_string(self):
        """#300's rule, honored: a shared token the ROSTER does not know is
        not a signal. `Northgate` is a proper noun in both sentences and
        resolves to nobody, so it contributes nothing."""
        self.assertEqual(
            self.views["classification:answers-a4#aaa4"].entities, frozenset())
        self.assertIn("theme/halcyon",
                      self.views["classification:answers-a1#aaa1"].entities)

    def test_a_key_too_short_to_be_a_name_resolves_nothing(self):
        """The floor `ENTITY_KEY_MIN_CHARS` sets. A three-letter theme would
        otherwise match a third of a life."""
        self.assertEqual(
            self.views["classification:answers-a5#aaa5"].entities, frozenset())
        self.assertEqual(ec.resolve_entities("ash everywhere", self.index), frozenset())
        self.assertEqual(ec.resolve_entities("halcyon works", self.index),
                         frozenset({"theme/halcyon"}))

    def test_a_place_that_already_scored_place_is_not_counted_twice(self):
        """ONE FACT, ONE SIGNAL — the live finding this rung's first run
        produced. Two tellings that share the place mention `Cedarport` score
        `place`; the same word resolving to `place/cedarport` out of their
        labels must NOT also score `entity`, or one fact would carry a pair
        over R1's floor by itself."""
        rows = [
            claim(source="classification:answers-b1#bbb1",
                  event_mention="Moved to Cedarport", event_kind="move",
                  place_mentions=["Cedarport"], quote="Moved to Cedarport."),
            claim(source="classification:answers-b2#bbb2",
                  event_mention="Moved to Cedarport", event_kind="move",
                  place_mentions=["Cedarport"], quote="We moved to Cedarport."),
        ]
        views = views_for(rows)
        units = eb.candidates(views)
        found = eb.independent_signals(
            views["classification:answers-b1#bbb1"],
            units["classification:answers-b2#bbb2"],
        )
        self.assertIn("place", found)
        self.assertNotIn(ec.ENTITY_SIGNAL, found)
        self.assertEqual(len(found), 1)

    def test_a_participant_that_already_scored_is_not_counted_twice(self):
        """The same subtraction under the other name. A shared resolved
        participant scores `participant`; the entity behind it is the same
        fact and is removed before the entities are counted."""
        counted = ec.shared_entities(
            {"person/wren-alder"}, {"person/wren-alder"},
            already_counted={"person/wren-alder"},
        )
        self.assertEqual(counted, frozenset())
        self.assertEqual(
            ec.shared_entities({"person/wren-alder"}, {"person/wren-alder"},
                               already_counted={"wren alder"}),
            frozenset(),
            "an unresolved participant MENTION must subtract its entity too",
        )
        self.assertEqual(
            ec.shared_entities({"theme/halcyon"}, {"theme/halcyon"},
                               already_counted={"person/wren-alder"}),
            frozenset({"theme/halcyon"}),
        )

    def test_it_never_binds_anything_on_its_own(self):
        """R1's floor is unchanged at two. A pair whose ONLY independent
        signal is the entity is a proposal, never a bind — proved by running
        the plan and finding no envelope over the entity-only pairs."""
        result = plan_for()
        for pair in result.pairs:
            detail = {row.name: row.detail for row in pair.conditions}
            if detail["two_independent_signals"].startswith("1 of 2"):
                self.assertNotEqual(pair.verdict, "bind")
        for envelope in result.envelopes:
            self.assertGreaterEqual(len(envelope["operation"]["members"]), 2)


# ==========================================================================
# §12b ruling 2 — what a container is
# ==========================================================================


class ContainerRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.views = views_for()
        self.result = plan_for()

    def test_a_started_claim_with_no_end_opens_an_open_ended_span(self):
        span, open_ended = ec.span_from_claims([
            claim(source=HALCYON, claim_type="date", subject_mention="Halcyon",
                  event_kind="started", temporal_value=value("2022-05")),
        ])
        self.assertTrue(open_ended)
        self.assertEqual(span.earliest, "2022-05")
        self.assertIsNone(span.latest)
        self.assertEqual(chrono.display_date(span, with_basis=False), "after May 2022")

    def test_an_ended_claim_closes_it(self):
        span, open_ended = ec.span_from_claims([
            claim(source=HALCYON_END, claim_type="date", subject_mention="Tidewheel",
                  event_kind="started", temporal_value=value("2018-11")),
            claim(source=HALCYON_END, claim_type="date", subject_mention="Tidewheel",
                  event_kind="ended", temporal_value=value("2021-01")),
        ])
        self.assertFalse(open_ended)
        self.assertEqual((span.earliest, span.latest), ("2018-11", "2021-01"))
        self.assertEqual(chrono.display_date(span, with_basis=False),
                         "November 2018–January 2021")

    def test_an_inherited_stretch_is_a_stretch_but_never_a_container(self):
        """v292 (R7): a schooling that took its stay's two ends HAS two ends —
        drawing only its start would publish a stretch nobody claimed as a
        point nobody named — but a container is opened *in the person's own
        words*, and an inherited span is not those. One body, one knob."""
        bounds = [
            claim(source=HALCYON_END, claim_type="date",
                  subject_mention="Kestrel Elementary", event_kind="started",
                  temporal_value=value("1986-06", basis="anchor")),
            claim(source=HALCYON_END, claim_type="date",
                  subject_mention="Kestrel Elementary", event_kind="ended",
                  temporal_value=value("1988-03", basis="anchor")),
        ]
        self.assertEqual(ec.span_from_claims(bounds), (None, False))
        span, open_ended = ec.span_from_claims(bounds, require_stated=False)
        self.assertFalse(open_ended)
        self.assertEqual((span.earliest, span.latest), ("1986-06", "1988-03"))
        # It says out loud that it was inherited rather than being stamped
        # with the person's own authority.
        self.assertEqual(span.basis, "anchor")

    def test_a_point_dated_moment_is_not_a_container(self):
        """The negative that keeps four hundred moments from becoming
        containers. `Wren Alder, born 2010-12-21` has a stated date and a
        resolved subject, and opens no stretch."""
        self.assertIsNone(self.views["landmark:entry-wren"].span)
        for container in self.result.containers.values():
            self.assertNotEqual(container.opened_by, "landmark:entry-wren")

    def test_a_container_needs_an_entity_of_its_own(self):
        """A span nobody can name is not a container: a member could never
        say it belongs there."""
        rows = [claim(source="landmark:entry-nameless", claim_type="date",
                      subject_mention="that whole stretch", event_kind="started",
                      temporal_value=value("2015"))]
        views = views_for(rows)
        self.assertIsNotNone(views["landmark:entry-nameless"].span)
        self.assertEqual(views["landmark:entry-nameless"].subject_entities, frozenset())
        self.assertEqual(
            ec.containers(views, eb.candidates(views)), {})

    def test_a_container_is_named_by_what_it_is_about(self):
        """Not by everything it mentions: the container's entities come from
        its SUBJECT mentions, so a span that merely names Halcyon in passing
        does not become Halcyon."""
        rows = [claim(source="landmark:entry-side", claim_type="date",
                      subject_mention="a job", event_kind="started",
                      event_mention="A job I took after Halcyon",
                      temporal_value=value("2015"))]
        views = views_for(rows)
        view = views["landmark:entry-side"]
        self.assertIn("theme/halcyon", view.entities)
        self.assertEqual(view.subject_entities, frozenset())
        self.assertEqual(ec.containers(views, eb.candidates(views)), {})

    def test_a_containers_id_is_minted_from_the_container_alone(self):
        """A container's identity may not depend on who joins it, or every
        new member would orphan every record already filed against it."""
        container = container_named(self.result, "Halcyon")
        self.assertEqual(container.episode_id, ec.container_episode_id(HALCYON))
        self.assertEqual(container.episode_id,
                         eb.prospective_episode_id([HALCYON]))
        with_more = plan_for(base_claims() + [
            claim(source="classification:answers-z9#zzz9",
                  event_mention="Another Halcyon thing", event_kind="moment"),
        ])
        self.assertEqual(container_named(with_more, "Halcyon").episode_id,
                         container.episode_id)


# ==========================================================================
# §12b ruling 2 — the `entity_span` rung
# ==========================================================================


class EntitySpanRungTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = plan_for()

    def test_an_undated_telling_naming_the_entity_is_placed(self):
        members = members_of(self.result, "Halcyon")
        row = members["classification:answers-a1#aaa1"]
        self.assertEqual(row["rule_id"], ec.RULE_ID_ENTITY_SPAN)
        self.assertFalse(row["dated"])
        self.assertIn("theme/halcyon", row["entities"])

    def test_a_dated_telling_inside_the_span_is_placed(self):
        row = members_of(self.result, "Halcyon")["classification:answers-a2#aaa2"]
        self.assertTrue(row["dated"])
        self.assertTrue(row["date_inside_span"])
        self.assertIn("dated inside the span", row["reason"])

    def test_a_dated_telling_outside_every_span_is_not_placed(self):
        """The negative. `Halcyon was only a daydream then`, dated 1999, names
        the entity and is outside both Halcyon spans — the rung leaves it for
        the person rather than moving its date to fit."""
        for label in ("Halcyon", "the idea for Halcyon"):
            self.assertNotIn("classification:answers-a3#aaa3",
                             members_of(self.result, label))

    def test_inside_means_inside_and_not_merely_compatible(self):
        outer = chrono.DateRecord(best="2022-05/..", earliest="2022-05", latest=None,
                                  granularity="range", basis="stated")
        self.assertTrue(ec.date_inside_span(
            chrono.from_dict(value("2023-04")), outer))
        self.assertFalse(ec.date_inside_span(
            chrono.from_dict(value("1999")), outer))
        self.assertFalse(
            ec.date_inside_span(chrono.from_dict(value("2022")), outer),
            "a year-granular date is not PROVABLY inside a span that starts in May",
        )

    def test_a_member_of_two_containers_holds_two_receipts(self):
        """§13.5: *a member of two containers renders in both*. The eras
        paradigm — a membership is a receipt, not a bound — and the reason C2's
        telling-level refusal narrowed to `same` in this phase."""
        both = members_of(self.result, "Halcyon").keys() & \
            members_of(self.result, "the idea for Halcyon").keys()
        self.assertIn("classification:answers-a1#aaa1", both)
        records = [row for row in self.result.proposals
                   if row["telling_ref"] == "classification:answers-a1#aaa1"]
        self.assertEqual(len(records), 2)
        self.assertEqual(len(ei.validate_identity_set(records)), 2)

    def test_a_container_is_never_placed_inside_itself(self):
        self.assertNotIn(HALCYON, members_of(self.result, "Halcyon"))


# ==========================================================================
# §12b ruling 5 — `question_context`
# ==========================================================================


class QuestionContextTests(unittest.TestCase):
    def test_an_answer_to_a_container_question_is_placed_with_no_entity(self):
        """The stamp is a FACT about what was asked, so it needs no entity
        agreement at all: `Northgate opened` names nobody the roster knows and
        still lands inside Halcyon when Halcyon is what was being asked."""
        result = plan_for(question_contexts={
            "classification:answers-a4#aaa4": ec.container_episode_id(HALCYON),
        })
        row = members_of(result, "Halcyon")["classification:answers-a4#aaa4"]
        self.assertEqual(row["rule_id"], ec.RULE_ID_QUESTION_CONTEXT)
        self.assertEqual(row["entities"], [])

    def test_the_stamp_may_name_the_container_three_ways(self):
        container = container_named(plan_for(), "Halcyon")
        for stamp in (container.episode_id, container.key, container.opened_by):
            result = plan_for(question_contexts={
                "classification:answers-a4#aaa4": stamp})
            self.assertIn("classification:answers-a4#aaa4",
                          members_of(result, "Halcyon"), stamp)

    def test_it_outranks_the_entity_rung_on_the_same_pair(self):
        result = plan_for(question_contexts={
            "classification:answers-a1#aaa1": ec.container_episode_id(HALCYON),
        })
        row = members_of(result, "Halcyon")["classification:answers-a1#aaa1"]
        self.assertEqual(row["rule_id"], ec.RULE_ID_QUESTION_CONTEXT)

    def test_a_dated_answer_outside_the_span_is_placed_and_says_so(self):
        """A stamp is not an inference, so it is not refused by a date — but
        the disagreement is RECORDED in the reason rather than swallowed, and
        §5.3 still forbids narrowing anything."""
        result = plan_for(question_contexts={
            "classification:answers-a3#aaa3": ec.container_episode_id(HALCYON),
        })
        row = members_of(result, "Halcyon")["classification:answers-a3#aaa3"]
        self.assertEqual(row["rule_id"], ec.RULE_ID_QUESTION_CONTEXT)
        self.assertIn("falls outside that span", row["reason"])

    def test_a_stamp_that_names_no_container_is_reported_never_guessed(self):
        """The negative. An era id, a work-item id the host did not resolve, a
        container that has been superseded — each is a named diagnostic and
        never a placement into whatever happened to be nearby."""
        result = plan_for(question_contexts={
            "classification:answers-a4#aaa4": "era:0123456789abcdef01234567",
        })
        self.assertNotIn("classification:answers-a4#aaa4",
                         members_of(result, "Halcyon"))
        self.assertEqual(
            [row["finding"] for row in result.containment_diagnostics],
            ["question_context_container_unknown"],
        )
        self.assertEqual(result.counts["unresolved_question_contexts"], 1)

    def test_the_stamp_rides_the_promoted_sources_own_frontmatter(self):
        """The seam, end to end: the recorder stamps `question_context` on the
        promoted source, and `read_question_contexts` hands the binder a
        `{telling_ref: container}` map off the vault."""
        root = root_parent_tmp(self, ROOT, prefix="i2b-stamp-")
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "sources").mkdir(parents=True, exist_ok=True)
        target = ec.container_episode_id(HALCYON)
        source_ref = ts.promote_conversational_source(
            root, "We shipped the first thing that summer.",
            {"session_ref": "chat:1", "turn_ref": "t1",
             ts.QUESTION_CONTEXT_KEY: target},
        )
        text = (root / source_ref.source_path).read_text("utf-8")
        self.assertIn(f'{ts.QUESTION_CONTEXT_KEY}: "{target}"', text)
        rows = [claim(source=source_ref.source_id, event_mention="We shipped it",
                      event_kind="moment")]
        rows[0]["source_ref"] = source_ref.to_dict()
        found = eb.read_question_contexts(root, rows)
        self.assertEqual(found, {source_ref.source_id: target})

    def test_the_stamp_is_not_part_of_a_sources_identity(self):
        """Two answers to two different questions saying the same words in the
        same turn are still ONE utterance: the stamp is outside
        `PROMOTION_IDENTITY_KEYS`."""
        meta = {"session_ref": "chat:1", "turn_ref": "t1"}
        first = ts.promotion_digest("the same words", meta)
        second = ts.promotion_digest(
            "the same words", {**meta, ts.QUESTION_CONTEXT_KEY: "episode:" + "a" * 24})
        self.assertEqual(first, second)


# ==========================================================================
# §12b ruling 5 — C2's origin gate, widened by exactly two rule ids
# ==========================================================================


class OriginGateTests(unittest.TestCase):
    def payload(self, **overrides) -> dict:
        row = {"telling_ref": "landmark:entry-1",
               "episode_id": "episode:" + "a" * 24,
               "relation": "part_of", "origin": "deterministic",
               "rule_version": efc.IDENTITY_RULE_VERSION,
               "rule_id": ec.RULE_ID_ENTITY_SPAN}
        row.update(overrides)
        return row

    def test_the_two_evidence_grade_rules_are_admitted(self):
        for rule_id in efc.DETERMINISTIC_CONTAINMENT_RULE_IDS:
            record = ei.validate_event_identity(self.payload(rule_id=rule_id))
            self.assertEqual(record["origin"], "deterministic")
            self.assertEqual(record["relation"], "part_of")

    def test_every_other_rule_id_is_refused(self):
        """The negative, both ways. §12b ruling 5 is a CLOSED widening."""
        for rule_id in ("R1-containment", "entity-span", "", None, "R1"):
            with self.assertRaises(ei.EventIdentityError) as caught:
                ei.validate_event_identity(self.payload(rule_id=rule_id))
            self.assertEqual(caught.exception.code,
                             "identity_deterministic_relation_unsupported")

    def test_the_other_relations_are_still_refused_at_deterministic(self):
        for relation in ("related", "not_same", "none"):
            with self.assertRaises(ei.EventIdentityError) as caught:
                ei.validate_event_identity(
                    self.payload(relation=relation,
                                 rule_id=ec.RULE_ID_ENTITY_SPAN))
            self.assertEqual(caught.exception.code,
                             "identity_deterministic_relation_unsupported")

    def test_same_needs_no_rule_id_at_all(self):
        record = ei.validate_event_identity(
            self.payload(relation="same", rule_id=None))
        self.assertEqual(record["relation"], "same")

    def test_the_language_rung_still_files_as_a_proposal(self):
        """I2's `part_of` rung reads prose and GUESSES, so it is not one of
        the two evidence-grade rules and never files deterministically."""
        self.assertNotIn(f"{eb.RULE_ID}-containment",
                         efc.DETERMINISTIC_CONTAINMENT_RULE_IDS)
        self.assertFalse(efc.deterministic_relation_allowed(
            "part_of", f"{eb.RULE_ID}-containment"))

    def test_the_predicate_has_one_home(self):
        """ADR 0021: the write door and the rung that mints the records read
        ONE tuple. A second assignment anywhere in `system/` is the drift this
        program exists to remove."""
        pattern = re.compile(r"^DETERMINISTIC_CONTAINMENT_RULE_IDS\s*=\s*\(", re.M)
        homes = [path.name for path in sorted((ROOT / "system").glob("*.py"))
                 if pattern.search(path.read_text("utf-8"))]
        self.assertEqual(homes, ["episode_fold_contract.py"])


# ==========================================================================
# §12b ruling 6 — the authority flag
# ==========================================================================


class AuthorityTests(unittest.TestCase):
    def test_the_flag_changes_exactly_one_field(self):
        """*Structure it so flipping the flag changes NOTHING about the
        records, only the fold's routing.* `origin` is outside
        `IDENTITY_IDENTITY_KEYS`, so the id, the rule, the evidence and the
        directory are identical and only the routing moves."""
        proposed = plan_for(containment_authority="proposed").proposals
        applied = plan_for(containment_authority="applied").proposals
        self.assertTrue(proposed)
        self.assertEqual(len(proposed), len(applied))
        for left, right in zip(proposed, applied):
            self.assertEqual(left["origin"], "proposed")
            self.assertEqual(right["origin"], "deterministic")
            self.assertEqual({k: v for k, v in left.items() if k != "origin"},
                             {k: v for k, v in right.items() if k != "origin"})
            self.assertEqual(ei.bindings_dir(left["origin"]),
                             ei.bindings_dir(right["origin"]))

    def test_proposed_is_the_default(self):
        self.assertEqual(efc.DEFAULT_CONTAINMENT_AUTHORITY, "proposed")
        self.assertEqual(plan_for().containment_authority, "proposed")
        self.assertEqual(plan_for().containment_block_name, "containment_proposals")
        self.assertEqual(plan_for(containment_authority="applied").containment_block_name,
                         "containments")

    def test_an_unknown_authority_is_refused_before_a_run_is_decided(self):
        with self.assertRaises(Exception) as caught:
            plan_for(containment_authority="auto")
        self.assertEqual(getattr(caught.exception, "code", ""),
                         "containment_authority_unknown")

    def test_the_flag_is_the_whole_difference_the_fold_sees(self):
        """`applied` lands in `containments`, `proposed` in `proposed_links` —
        the routing `GROUPING_ORIGINS` already decided, reached by one flag."""
        claims = base_claims()
        for authority, key, other in (("applied", "containments", "proposed_links"),
                                      ("proposed", "proposed_links", "containments")):
            result = plan_for(claims, containment_authority=authority)
            records = ef.normalize_episode_records(
                {"bindings": list(result.proposals)})
            found = tt.derive_calculated_timeline(
                {"version": ts.INDEX_VERSION, "claims": claims},
                episode_records=records, now=NOW,
            )
            nodes = [node for node in found.nodes if node.get(key)]
            self.assertTrue(nodes, authority)
            self.assertFalse([node for node in found.nodes if node.get(other)],
                             authority)


# ==========================================================================
# §5.3 — containment never narrows a date
# ==========================================================================


class ContainmentNarrowsNothingTests(unittest.TestCase):
    def timeline(self, *, authority="applied"):
        claims = base_claims()
        result = plan_for(claims, containment_authority=authority)
        records = ef.normalize_episode_records({"bindings": list(result.proposals)})
        return claims, tt.derive_calculated_timeline(
            {"version": ts.INDEX_VERSION, "claims": claims},
            episode_records=records, now=NOW,
        )

    def node_for(self, found, label):
        for node in found.nodes:
            if node.get("label") == label:
                return node
        raise AssertionError(f"no node labelled {label!r}")

    def test_a_dated_member_keeps_its_own_value(self):
        _claims, found = self.timeline()
        node = self.node_for(found, "Halcyon's first customer")
        self.assertEqual(chrono.from_dict(node["best_temporal_value"]).best, "2023-04")
        self.assertIsNone(node.get("possible_temporal_value"))

    def test_an_undated_member_is_still_undated(self):
        _claims, found = self.timeline()
        node = self.node_for(found, "Started Halcyon")
        self.assertIsNone(node.get("best_temporal_value"))

    def test_the_containment_is_published_on_the_member(self):
        _claims, found = self.timeline()
        node = self.node_for(found, "Started Halcyon")
        self.assertEqual(len(node["containments"]), 2)
        for row in node["containments"]:
            self.assertEqual(row["relation"], "part_of")
            self.assertEqual(row["origin"], "deterministic")


# ==========================================================================
# §13.5 — the dry run, the seams, and determinism
# ==========================================================================


class DryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = plan_for()

    def test_it_reports_containments_per_container_with_per_pair_reasons(self):
        lines = eb.describe(self.result)
        text = "\n".join(lines)
        self.assertIn("containment_proposals", text)
        self.assertIn("Halcyon", text)
        for block in self.result.containments:
            self.assertIn(block["episode_id"], text)
            for member in block["members"]:
                self.assertIn(member["reason"], text)
                self.assertIn(member["rule_id"], ec.DETERMINISTIC_CONTAINMENT_RULE_IDS)

    def test_the_counts_say_what_they_count(self):
        counts = self.result.counts
        self.assertEqual(counts["containers"], len(self.result.containers))
        self.assertEqual(
            counts["containment_members"],
            sum(len(block["members"]) for block in self.result.containments))
        self.assertEqual(
            counts["containment_by_rule"][ec.RULE_ID_ENTITY_SPAN],
            counts["containment_members"])
        self.assertEqual(counts["containment_authority"], "proposed")

    def test_the_report_names_the_block_the_authority_earns(self):
        applied = eb.describe(plan_for(containment_authority="applied"))
        self.assertIn("containments (", "\n".join(applied))
        self.assertNotIn("containment_proposals", "\n".join(applied))

    def test_the_plan_is_deterministic(self):
        self.assertEqual(plan_for().as_dict(), plan_for().as_dict())

    def test_the_block_is_ordered_by_size_then_id(self):
        sizes = [(-block["member_count"], block["episode_id"])
                 for block in self.result.containments]
        self.assertEqual(sizes, sorted(sizes))


class VaultSeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="i2b-vault-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        seed_vault(self.root, base_claims())
        seed_rosters(self.root)

    def files(self) -> set:
        return {path.relative_to(self.root).as_posix()
                for path in self.root.rglob("*") if path.is_file()}

    def test_the_rosters_reach_the_binder_off_the_vault(self):
        index = ec.load_entity_index(self.root)
        self.assertGreaterEqual(index.size(), 4)
        self.assertEqual(index.name_of("theme/halcyon"), "Halcyon")

    def test_a_vault_with_no_rosters_scores_one_signal_fewer_and_no_error(self):
        for path in (self.root / "state" / "entity_rosters").glob("*.json"):
            path.unlink()
        outcome = eb.bind_episodes(self.root, apply=False, now=NOW)
        self.assertEqual(outcome["entities"], 0)
        self.assertEqual(outcome["plan"].counts["containers"], 0)

    def test_the_weekly_step_runs_the_rung_and_writes_nothing(self):
        """§12b ruling 7: placing happens in the weekly sweep, at answer time
        and in operator runs — all three are this one `plan()`, and the
        maintenance seat is still a dry run by construction."""
        before = self.files()
        outcome = eb.binder_step(self.root, now=NOW)
        self.assertFalse(outcome["wrote"])
        self.assertEqual(self.files(), before)
        self.assertTrue(outcome["containment_proposals"])
        self.assertEqual(outcome["counts"]["containers"], 3)

    def test_the_operator_run_files_them_and_replay_is_a_no_op(self):
        first = eb.bind_episodes(self.root, apply=True, now=NOW,
                                 containment_authority="applied")
        self.assertEqual(len(first["filed"]["proposals"]),
                         first["plan"].counts["containment_members"])
        self.assertEqual(first["filed"]["created"],
                         len(first["filed"]["proposals"]))
        second = eb.bind_episodes(self.root, apply=True,
                                  now="2027-01-01T00:00:00Z",
                                  containment_authority="applied")
        self.assertEqual(second["filed"]["created"], 0)
        loaded = ef.load_episode_records(self.root)
        self.assertEqual(len(loaded["bindings"]),
                         first["plan"].counts["containment_members"])

    def test_a_dry_run_still_writes_not_one_byte(self):
        before = self.files()
        eb.bind_episodes(self.root, apply=False, now=NOW,
                         containment_authority="applied")
        self.assertEqual(self.files(), before)

    def test_the_deterministic_records_live_under_state(self):
        eb.bind_episodes(self.root, apply=True, now=NOW,
                         containment_authority="applied")
        written = [name for name in self.files()
                   if "identities/bindings" in name]
        self.assertTrue(written)
        for name in written:
            self.assertTrue(name.startswith("state/"), name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
