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
import episode_containers as ec  # noqa: E402
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
