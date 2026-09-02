"""E-L2a row 24 — a residence, a job and a school reach the containment rung.

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1, §0.2
M1–M3, §3.2, §4.1, §4.2, §4.4 and acceptance row 24, plus OSS ADR 0030's
participation-episode addendum. The finding this file exists for, in the
design's own words:

    *the place co-location rule cannot fire from the landmark ladder today.*

`landmark_projection.entry_claims` files a residence/school/work/military span
as two DOMAIN-AGNOSTIC ``started``/``ended`` point claims; the retired
`place_co_location` pass fired only on episode groups whose ``event_kind`` was
in ``COLOCATION_EPISODE_KINDS`` and nothing in production ever emitted one of
those kinds; and the binder's own `_canonical_kind` resolved a residence to the
literal ``started``, which the family table files under ``work``. The result:
a residence a person filed in conversation could never contain a story, and
`tests/test_place_co_location.py` said so at its own line 24 — every case there
was built from claims by hand that no pipeline produces.

So every case below runs through the REAL path and nothing else: the recorder's
own writer (`landmark_projection.file_landmark_record`, which is what
`landmark-record` and the hosts' `landmark_invocations` call), the promoted
source, the receipt, the active index, `bind-episodes` and the fold. If a
substrate change stops reaching the recorder, these tests go red.

Synthetic data only; NEVER references ~/Workspace/dave.
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
import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"

#: Synthetic rosters. The place and the two organizations are what makes an
#: undated story's mention of them EVIDENCE rather than a shared string
#: (`episode_containers.ENTITY_SIGNAL_INDEPENDENCE_TEXT`).
ROSTERS = {
    "place": {"type": "place", "entities": [
        {"name": "Cedarport", "slug": "cedarport",
         "aliases": ["the Cedarport house"]},
        {"name": "Millgate", "slug": "millgate", "aliases": []},
    ]},
    "object": {"type": "object", "entities": [
        {"name": "Tidewheel Works", "slug": "tidewheel-works",
         "aliases": ["Tidewheel"]},
        {"name": "Alder Ridge High", "slug": "alder-ridge-high",
         "aliases": ["Alder Ridge"]},
    ]},
}


def value(text: str, *, basis: str = "stated") -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": basis, "confidence": "certain"}


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def story_claim(source: str, mention: str, quote: str, *,
                temporal_value: object = None) -> dict:
    """One classifier-shaped telling, exactly as `classifier_claims` files it."""
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": quote}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": "occurrence",
        "subject_mention": "I",
        "event_mention": mention,
        "event_kind": "moment",
        "event_ref": tp.derive_node_id(
            node_kind="event", event_kind="moment",
            subject_refs=["I"], discriminator=source,
        ),
    }
    if temporal_value is not None:
        payload["claim_type"] = "date"
        payload["temporal_value"] = temporal_value
    return tc.validate_temporal_claim(payload)


class ParticipationEpisodeCase(unittest.TestCase):
    """One synthetic vault, built through the recorder, folded once."""

    #: The landmark entries this case files, in filing order. A recorder record
    #: carries the leaf's own `label` AND the domain's identity rung, which is
    #: the shape `landmarks_interaction.validate_landmark` normalizes and the
    #: shape the #586 audit found on the founder's own vault.
    ENTRIES: tuple = (
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": {"start": value("1996-06"), "end": value("2001-08")}}),
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": {"start": value("2002-03"), "end": value("2006-09")}}),
        ("schools", {"label": "Alder Ridge High", "name": "Alder Ridge High",
                     "span": {"start": value("1994-09"), "end": value("1998-06")}}),
    )

    STORIES: tuple = (
        ("classification:answers-a1#aaa1",
         "The tree fell on the Cedarport house",
         "A storm dropped a tree on the Cedarport house."),
        ("classification:answers-a2#aaa2",
         "The Tidewheel Works picnic",
         "Tidewheel Works held a picnic by the river."),
        ("classification:answers-a3#aaa3",
         "The Alder Ridge High assembly",
         "Alder Ridge High put on an assembly nobody forgot."),
    )

    AUTHORITY = "applied"

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="el2a-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        rosters = self.root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        for kind, snapshot in ROSTERS.items():
            (rosters / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")

        self.filed = []
        for ordinal, (domain, entry) in enumerate(self.ENTRIES, start=1):
            self.filed.append(
                lp.file_landmark_record(self.root, domain, entry,
                                        ordinal=ordinal, now=NOW)
            )
        for source, mention, quote in self.STORIES:
            row = story_claim(source, mention, quote)
            ts.write_receipt(self.root, {
                "source_ref": row["source_ref"],
                "extractor_version": "classifier:1",
                "created_at": "2026-08-30T00:00:00Z",
                "claims": [row],
            })
        ts.rebuild_active_index(self.root)

        self.binder = eb.bind_episodes(
            self.root, apply=True, now=NOW,
            containment_authority=self.AUTHORITY,
        )
        self.timeline = self.fold()

    def fold(self):
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.root),
            episode_records=ef.load_episode_records(self.root),
            landmark_entries=lp.load_landmark_sources(self.root),
            now=NOW,
        )

    # -- helpers ---------------------------------------------------------

    def node_of_kind(self, event_kind: str, label: str) -> dict:
        found = [row for row in self.timeline.nodes
                 if row["event_kind"] == event_kind and row["label"] == label]
        self.assertEqual(
            len(found), 1,
            f"expected exactly one {event_kind!r} node labelled {label!r}; "
            f"the vault holds "
            f"{sorted((r['event_kind'], r['label']) for r in self.timeline.nodes)}",
        )
        return found[0]

    def node_labelled(self, label: str) -> dict:
        found = [row for row in self.timeline.nodes if row["label"] == label]
        self.assertEqual(len(found), 1, f"no single node labelled {label!r}")
        return found[0]

    def span_text(self, record: object) -> str:
        return chrono.display_date(chrono.from_dict(record), with_basis=False)


class ARecordedStayIsAnEpisode(ParticipationEpisodeCase):
    """Row 24, leg (a): the landmark's own span IS one participation episode."""

    def test_a_residence_folds_to_one_residence_episode_with_a_duration(self):
        node = self.node_of_kind("residence", "Cedarport")
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(self.span_text(node.get("best_temporal_value")),
                         "June 1996–August 2001")

    def test_a_job_folds_to_one_job_episode_with_a_duration(self):
        node = self.node_of_kind("job", "Tidewheel Works")
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(self.span_text(node.get("best_temporal_value")),
                         "March 2002–September 2006")

    def test_a_school_folds_to_one_school_episode_with_a_duration(self):
        node = self.node_of_kind("school", "Alder Ridge High")
        self.assertEqual(node["node_kind"], "episode")
        self.assertEqual(self.span_text(node.get("best_temporal_value")),
                         "September 1994–June 1998")

    def test_the_two_ends_are_not_two_loose_point_nodes(self):
        """The defect's own signature: `started` and `ended` nodes, one per
        end, neither of which is a stretch anything can be inside."""
        loose = sorted(row["label"] for row in self.timeline.nodes
                       if row["event_kind"] in ("started", "ended"))
        self.assertEqual(loose, [])


class AStoryLandsInsideTheStay(ParticipationEpisodeCase):
    """Row 24, legs (b) and (c): the rung binds, and the window is the span."""

    def containment(self, label: str) -> dict:
        node = self.node_labelled(label)
        rows = node.get("containments") or []
        self.assertEqual(len(rows), 1, f"{label!r}: {json.dumps(rows, default=str)}")
        return rows[0]

    def test_the_story_is_part_of_the_residence_episode(self):
        row = self.containment("The tree fell on the Cedarport house")
        self.assertEqual(row["relation"], "part_of")
        self.assertEqual(row["origin"], "deterministic")
        self.assertEqual(row["episode_node_id"],
                         self.node_of_kind("residence", "Cedarport")["node_id"])

    def test_the_rung_that_filed_it_is_entity_span(self):
        by_rule = self.binder["plan"].counts["containment_by_rule"]
        self.assertEqual(by_rule["entity_span"], len(self.STORIES))
        self.assertEqual(by_rule["question_context"], 0)

    def test_the_member_renders_the_stay_as_its_possible_outer_range(self):
        node = self.node_labelled("The tree fell on the Cedarport house")
        self.assertIsNone(node.get("best_temporal_value"))
        self.assertEqual(self.span_text(node.get("possible_temporal_value")),
                         "June 1996–August 2001")

    def test_a_job_story_gets_the_tenure_as_its_window(self):
        node = self.node_labelled("The Tidewheel Works picnic")
        self.assertEqual(self.span_text(node.get("possible_temporal_value")),
                         "March 2002–September 2006")

    def test_the_window_does_not_silence_the_precision_question(self):
        """§7.1 / H6: render-placeable is not date-resolved. The anchored
        probe is an improvement on the question, never its removal."""
        node = self.node_labelled("The tree fell on the Cedarport house")
        kinds = {row["kind"] for row in self.timeline.work_items
                 if row.get("event_ref") == node["node_id"]}
        self.assertIn("precision_gap", kinds)


class TwoStaysAtOnePlace(ParticipationEpisodeCase):
    """§4.1 condition 4 — the rung refuses, and the substrate asks instead.

    The case `tests/test_place_co_location.py` proved on hand-built claims,
    re-hosted on the real path: a person who lived in one place twice has TWO
    residence episodes (`identity_resolution.derive_episode_ref` will not
    collapse them), and an undated story naming that place belongs to one of
    them and nobody knows which.
    """

    ENTRIES = (
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": {"start": value("1988"), "end": value("1990")}}),
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": {"start": value("1996"), "end": value("1999")}}),
    )
    STORIES = (
        ("classification:answers-a1#aaa1",
         "The zoo trip in Cedarport",
         "We went to the zoo in Cedarport."),
    )

    def test_two_stays_at_one_place_are_two_episodes(self):
        stays = [row for row in self.timeline.nodes
                 if row["event_kind"] == "residence"]
        self.assertEqual(len(stays), 2)
        self.assertEqual(
            sorted(self.span_text(row["best_temporal_value"]) for row in stays),
            ["1988–1990", "1996–1999"],
        )

    def test_the_rung_files_no_containment_and_says_why(self):
        plan = self.binder["plan"]
        self.assertEqual(plan.counts["containment_by_rule"]["entity_span"], 0)
        refused = plan.containment_ambiguities
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["entity"], "place/cedarport")
        self.assertEqual(refused[0]["kind"], "place_ambiguous")
        self.assertEqual(len(refused[0]["episode_ids"]), 2)

    def test_one_place_ambiguous_item_names_both_stretches(self):
        items = [row for row in self.timeline.work_items
                 if row["kind"] == "place_ambiguous"]
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["prompt_intent"],
            "Which time in Cedarport was this — 1988–1990 or 1996–1999?",
        )

    def test_the_member_is_left_unplaced_rather_than_guessed(self):
        node = self.node_labelled("The zoo trip in Cedarport")
        self.assertIsNone(node.get("best_temporal_value"))
        self.assertIsNone(node.get("possible_temporal_value"))


class TwoTenuresAtOneEmployer(ParticipationEpisodeCase):
    """The same refusal for an organization, under its own kind (§7.2)."""

    ENTRIES = (
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": {"start": value("2002"), "end": value("2004")}}),
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": {"start": value("2010"), "end": value("2013")}}),
    )
    STORIES = (
        ("classification:answers-a2#aaa2",
         "The Tidewheel Works river picnic",
         "Tidewheel Works held a picnic by the river."),
    )

    def test_the_item_is_tenure_ambiguous_and_asks_at_not_in(self):
        items = [row for row in self.timeline.work_items
                 if row["kind"] == "tenure_ambiguous"]
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["prompt_intent"],
            "Which time at Tidewheel Works was this — 2002–2004 or 2010–2013?",
        )

    def test_the_refusal_names_the_organization_kind(self):
        refused = self.binder["plan"].containment_ambiguities
        self.assertEqual([row["kind"] for row in refused], ["tenure_ambiguous"])


class AnUndatedStay(ParticipationEpisodeCase):
    """§3.2 M3 — an undated stay is an episode, and never a container."""

    ENTRIES = (
        ("residences", {"label": "Millgate", "city": "Millgate"}),
    )
    STORIES = (
        ("classification:answers-a1#aaa1",
         "The winter the pipes froze",
         "The pipes froze that winter in Millgate."),
    )

    def test_it_folds_to_an_episode_with_no_value(self):
        node = self.node_of_kind("residence", "Millgate")
        self.assertEqual(node["node_kind"], "episode")
        self.assertIsNone(node.get("best_temporal_value"))

    def test_it_is_never_a_container(self):
        """No span, no window — structurally, in
        `episode_containers.containers`, which requires a telling that OPENS
        a span before a unit is a container at all."""
        self.assertEqual(self.binder["plan"].containers, {})
        self.assertEqual(
            self.binder["plan"].counts["containment_members"], 0)
        node = self.node_labelled("The winter the pipes froze")
        self.assertIsNone(node.get("possible_temporal_value"))

    def test_a_stated_start_re_keys_it_and_publishes_the_old_id(self):
        """§3.2 M3's second half. The re-key is DERIVED, not remembered: both
        ids are pure functions of the same entry, so the alias survives a
        `state/` deletion the way event identity's own Law 5 aliases do."""
        import landmark_projection as lp2
        before = self.node_of_kind("residence", "Millgate")["node_id"]
        self.assertEqual(self.timeline.node_aliases, {})

        lp2.file_landmark_record(
            self.root, "residences",
            {"label": "Millgate", "city": "Millgate",
             "span": {"start": value("1992-04"), "end": value("1995-11")}},
            ordinal=99, now=NOW,
        )
        ts.rebuild_active_index(self.root)
        self.timeline = self.fold()
        dated = [row for row in self.timeline.nodes
                 if row["event_kind"] == "residence"
                 and row.get("best_temporal_value")]
        self.assertEqual(len(dated), 1)
        self.assertNotEqual(dated[0]["node_id"], before)
        self.assertEqual(self.timeline.node_aliases.get(
            self.unplaced_id_for(dated[0])), dated[0]["node_id"])

    def unplaced_id_for(self, node: dict) -> str:
        import identity_resolution as ident
        import landmark_projection as lp2
        for row in lp2.load_landmark_sources(self.root):
            if row["domain"] != "residences" or row["record"].get("span"):
                continue
            return ident.derive_episode_ref(
                event_kind="residence", subject_mention="Millgate",
                discriminator=row["source_id"],
            )
        raise AssertionError("no undated Millgate entry")

    def test_its_id_is_discriminated_by_its_own_promoted_source(self):
        """Two undated stays at one place stay two, because the discriminator
        is the promoted source id and no two entries share one."""
        import landmark_projection as lp2
        rows = lp2.load_landmark_sources(self.root)
        index = lp2.ParticipationEpisodes(
            ts.fold_active_index(self.root)["claims"], rows)
        node = self.node_of_kind("residence", "Millgate")
        self.assertTrue(index.is_unplaced(node["node_id"]))


class AMemberOfTwoContainers(ParticipationEpisodeCase):
    """§4.2 — windows across several containments INTERSECT."""

    ENTRIES = (
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": {"start": value("1996-06"), "end": value("2004-01")}}),
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": {"start": value("2000-03"), "end": value("2009-09")}}),
    )
    STORIES = (
        ("classification:answers-a1#aaa1",
         "The Cedarport roof leak, the Tidewheel Works year",
         "The roof leaked at the Cedarport house while I was at Tidewheel Works."),
    )

    def test_the_window_is_the_intersection_of_both_spans(self):
        node = self.node_labelled("The Cedarport roof leak, the Tidewheel Works year")
        rows = node.get("containments") or []
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.span_text(node.get("possible_temporal_value")),
                         "March 2000–January 2004")


class ContainmentsThatCannotBothHold(ParticipationEpisodeCase):
    """§4.2 — an empty intersection draws NOTHING and mints one contradiction."""

    ENTRIES = (
        ("residences", {"label": "Cedarport", "city": "Cedarport",
                        "span": {"start": value("1988"), "end": value("1990")}}),
        ("work", {"label": "Tidewheel Works", "what": "Tidewheel Works",
                  "span": {"start": value("2002"), "end": value("2006")}}),
    )
    STORIES = (
        ("classification:answers-a1#aaa1",
         "The Cedarport roof leak, the Tidewheel Works year",
         "The roof leaked at the Cedarport house while I was at Tidewheel Works."),
    )

    def test_no_window_is_drawn(self):
        node = self.node_labelled("The Cedarport roof leak, the Tidewheel Works year")
        self.assertEqual(len(node.get("containments") or []), 2)
        self.assertIsNone(node.get("possible_temporal_value"))

    def test_one_contradiction_cites_both_containments(self):
        node = self.node_labelled("The Cedarport roof leak, the Tidewheel Works year")
        items = [row for row in self.timeline.work_items
                 if row["kind"] == "contradiction"
                 and row.get("event_ref") == node["node_id"]]
        self.assertEqual(len(items), 1)


class ADwellingIsNotAJob(ParticipationEpisodeCase):
    """§0.2 M1's other half — the binder's own family table.

    `_kind_of` read a residence telling's claims, found ``started``, and
    :data:`episode_binder.KIND_FAMILIES` files ``started`` under ``work``. So a
    house and a job were in one family, a house was in none of its own, and
    ``_canonical_kind`` resolved a stay to the literal ``started``. The kind is
    the landmark DOMAIN now, read off the promoted source
    (`landmark_projection.participation_kinds_by_telling`), so the fold and the
    binder cannot disagree about what a house is.
    """

    def views(self) -> dict:
        return self.binder["plan"].views

    def view_labelled(self, label: str):
        found = [row for row in self.views().values() if row.label == label]
        self.assertEqual(len(found), 1, f"no single telling labelled {label!r}")
        return found[0]

    def test_a_residence_telling_declares_its_domains_kind(self):
        self.assertEqual(self.view_labelled("Cedarport").event_kind, "residence")
        self.assertEqual(self.view_labelled("Tidewheel Works").event_kind, "job")
        self.assertEqual(self.view_labelled("Alder Ridge High").event_kind, "school")

    def test_a_residence_is_in_the_dwelling_family_and_not_in_work(self):
        self.assertEqual(eb.kind_families("residence"), frozenset({"dwelling"}))
        self.assertEqual(eb.kind_families("job"), frozenset({"work"}))
        self.assertEqual(eb.kind_families("school"), frozenset({"schooling"}))
        self.assertFalse(eb.kinds_compatible("residence", "job"))

    def test_the_bare_span_boundaries_are_what_the_family_table_read(self):
        """Proven, not asserted: ``started`` really is in the ``work`` family,
        which is exactly why reading it as a residence's kind misfiled a
        house. The table is unchanged — a classifier may still emit
        ``started`` about a job — and what changed is that a LANDMARK telling
        no longer arrives wearing it."""
        self.assertIn("work", eb.kind_families("started"))
        self.assertNotIn("dwelling", eb.kind_families("started"))

    def test_a_caller_that_passes_no_landmark_entries_degrades_quietly(self):
        """The same shape `entity_index` already has: the rung loses the
        domain-typed kind and nothing else, and nothing is guessed."""
        claims = ts.fold_active_index(self.root)["claims"]
        without = eb.plan(claims, now=NOW)
        kinds = {row.label: row.event_kind for row in without.views.values()}
        self.assertIn(kinds["Cedarport"], ("started", "ended"))
        self.assertEqual(self.view_labelled("Cedarport").event_kind, "residence")


class TheWorkAndSchoolJoins(unittest.TestCase):
    """§4.4 / M6 — *"right after I started at {job}"* dates like a move does.

    Against v275 `JOINS` held ``move_in``/``move_out``/``graduation`` and
    nothing for work at all, so the design draft's claim that cross-dating
    "already does this" for a job was simply false.
    """

    ANCHORS = {
        "residences-cedarport-1": {
            "label": "Cedarport", "kind": "residence",
            "date": {"best": "1996-06/2001-08", "earliest": "1996-06",
                     "latest": "2001-08", "granularity": "month",
                     "basis": "stated", "confidence": "certain"},
        },
        "work-tidewheel-works-1": {
            "label": "Tidewheel Works", "kind": "period",
            "date": {"best": "2002-03/2006-09", "earliest": "2002-03",
                     "latest": "2006-09", "granularity": "month",
                     "basis": "stated", "confidence": "certain"},
        },
        "schools-alder-ridge-high-1": {
            "label": "Alder Ridge High", "kind": "period",
            "date": {"best": "1994-09/1998-06", "earliest": "1994-09",
                     "latest": "1998-06", "granularity": "month",
                     "basis": "stated", "confidence": "certain"},
        },
    }

    def derive(self, title: str):
        import cross_dating as cd
        return cd.definitional({"title": title}, self.ANCHORS)

    def test_the_four_new_joins_are_declared(self):
        import cross_dating as cd
        for join in ("job_start", "job_end", "school_start", "school_end"):
            self.assertIn(join, cd.JOINS)

    def test_a_job_start_dates_the_way_a_move_in_does(self):
        move = self.derive("Right after we moved to Cedarport")
        job = self.derive("Right after I started at Tidewheel Works")
        self.assertEqual(move.join, "move_in")
        self.assertEqual(job.join, "job_start")
        self.assertEqual(job.record.earliest, "2002-03")
        self.assertEqual(job.provenance, "from when you started at Tidewheel Works")

    def test_a_job_end_takes_the_far_bound(self):
        found = self.derive("I quit Tidewheel Works that autumn")
        self.assertEqual(found.join, "job_end")
        self.assertEqual(found.record.latest, "2006-09")

    def test_a_school_start_and_end_both_join(self):
        started = self.derive("I started at Alder Ridge High that year")
        self.assertEqual(started.join, "school_start")
        self.assertEqual(started.record.earliest, "1994-09")
        finished = self.derive("The year I dropped out of Alder Ridge High")
        self.assertEqual(finished.join, "school_end")
        self.assertEqual(finished.record.latest, "1998-06")

    def test_graduation_still_wins_where_it_always_did(self):
        found = self.derive("The week I graduated from Alder Ridge High")
        self.assertEqual(found.join, "graduation")

    def test_a_sentence_that_names_no_landmark_joins_nothing(self):
        self.assertIsNone(self.derive("I started at that place downtown"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
