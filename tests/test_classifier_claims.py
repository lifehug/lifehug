"""Timeline Fix 05 item 8.1 — every classifier moment becomes a claim.

Contract: lifehug-platform `docs/pr-specs/timeline-fix/05-one-timeline.md`
§8.1 and its test list §8.6 rows 1–5. Controlling designs: `docs/design/
eras.md` §5.1/§5.6/§5 and `docs/design/temporal-claims.md`.

Every negative test here was run against the unmodified v262 revision first
and SEEN failing; the outputs are in the PR body.

Synthetic data only, shaped like the founder's vault (a few classifications
whose `events[]` carry title/description/date/places/people, one of them over
a source a recorder already filed a claim against). NEVER references
~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import classifier_claims as cc  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-29T12:00:00Z"
BIRTH = "1981-07-11"


# --------------------------------------------------------------------------
# A synthetic vault, shaped like the real one
# --------------------------------------------------------------------------


def _vault(case: unittest.TestCase) -> Path:
    root = root_parent_tmp(case, ROOT, prefix="classifier-claims-")
    (root / "state" / "classifications").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "stories").mkdir(parents=True, exist_ok=True)
    return root


def _story(root: Path, name: str, text: str = "A story.") -> str:
    relative = f"sources/stories/{name}.md"
    path = root / relative
    path.write_text(
        f"---\ntitle: {name}\ntype: story\n---\n\n{text}\n", encoding="utf-8"
    )
    return relative


def _classification(root: Path, stem: str, payload: dict) -> Path:
    path = root / "state" / "classifications" / f"{stem}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def event(
    title: str,
    description: str,
    *,
    date: dict | None = None,
    when_hint: str | None = None,
    anchor: str | None = None,
    **extra: object,
) -> dict:
    """One classifier event in the shape `classify_story.build_prompt` asks for."""
    row: dict = {
        "title": title,
        "description": description,
        "when_hint": when_hint,
        "anchor": anchor,
        "date": date,
    }
    row.update(extra)
    return row


def classification(source_path: str, *events: dict, **extra: object) -> dict:
    payload: dict = {
        "source_path": source_path,
        "people": [],
        "places": [],
        "time_periods": [],
        "themes": [],
        "events": list(events),
    }
    payload.update(extra)
    return payload


def person(name: str, **extra: object) -> dict:
    row = {"name": name, "slug": name.lower().replace(" ", "-")}
    row.update(extra)
    return row


def roster(*entities: dict) -> dict:
    return {"type": "person", "entities": list(entities)}


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run(root: Path, **kwargs: object) -> dict:
    return cc.migrate_classifier_moments(
        root,
        classifications_dir=root / "state" / "classifications",
        dry_run=False,
        now=NOW,
        **kwargs,
    )


def _fold(root: Path, *, roster_snapshot: object = ()) -> tt.CalculatedTimeline:
    return tt.derive_calculated_timeline(
        ts.fold_active_index(root),
        roster_snapshot=roster_snapshot,
        now=NOW,
    )


def _birth_receipt(root: Path, relative: str) -> dict:
    """The owner's birthday, filed by the recorder, so the frames exist."""
    claim = tc.validate_temporal_claim(
        {
            "claim_type": "date",
            "subject_mention": "self",
            "event_kind": "birth",
            "temporal_value": BIRTH,
            "evidence": "I was born on 11 July 1981",
            "source_kind": "conversation",
            "source_ref": {
                "source_id": "conversation:msg-birth",
                "revision": "sha256:" + "9" * 64,
                "source_path": relative,
            },
            "extractor_version": "landmark_recorder/rule:1",
        },
        now=NOW,
    )
    ts.write_receipt(
        root,
        {
            "source_ref": claim["source_ref"],
            "extractor_version": "landmark_recorder/rule:1",
            "claims": [claim],
        },
        now=NOW,
    )
    return claim


# --------------------------------------------------------------------------
# 1 — one claim per event, and the right kind of claim
# --------------------------------------------------------------------------


class ClaimsPerEventTests(unittest.TestCase):
    """§8.6 row 1. Three events, three claims, three types, one revision."""

    def setUp(self):
        self.root = _vault(self)
        self.relative = _story(self.root, "the-move")
        self.payload = classification(
            self.relative,
            event("The Williams house", "We moved into the Williams house.",
                  date={"stated": "1988", "age": None, "anchor_ref": None,
                        "relation": None}),
            event("The bike with no brakes", "I rode a bike with no brakes.",
                  date={"stated": None, "age": "about five", "anchor_ref": None,
                        "relation": None}),
            event("Grandpa's two-page letter", "Grandpa wrote me two pages.",
                  when_hint="sixth grade", anchor="the move to Mesa"),
        )
        _classification(self.root, "the-move", self.payload)

    def test_three_events_become_three_claims_of_three_types(self):
        report = _run(self.root, publish=False)
        self.assertEqual(report["events"], 3)
        self.assertEqual(report["claims"], 3)
        self.assertEqual(
            report["claims_by_type"],
            {"date": 1, "age": 1, "relative_order": 0, "occurrence": 1},
        )
        rows = ts.active_claims(ts.fold_active_index(self.root))
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            sorted(row["claim_type"] for row in rows), ["age", "date", "occurrence"]
        )

    def test_every_claim_cites_the_classification_revision_and_the_story(self):
        _run(self.root, publish=False)
        revision = cc.classification_revision(self.payload)
        self.assertTrue(revision.startswith("sha256:"))
        for row in ts.active_claims(ts.fold_active_index(self.root)):
            self.assertEqual(row["source_ref"]["revision"], revision)
            self.assertEqual(row["source_ref"]["source_path"], self.relative)
            self.assertTrue(
                cc.is_classifier_source_id(row["source_ref"]["source_id"]),
                row["source_ref"],
            )
            self.assertEqual(row["extractor_version"], cc.CLASSIFIER_EXTRACTOR)

    def test_the_title_becomes_the_node_label_and_not_a_kind_word(self):
        # P5, from the founder's own page: never "I — moment".
        _run(self.root, publish=False)
        labels = {node["label"] for node in _fold(self.root).nodes}
        self.assertIn("The Williams house", labels)
        for label in labels:
            self.assertNotIn(" — moment", label)

    def test_a_when_hint_is_evidence_and_never_a_parsed_age(self):
        # chronology.parse_age is a FIELD parser: over free text it reads
        # "two weeks after the wedding" as age 2 and "1985" as age 5. The
        # migration must never hand it one.
        self.assertEqual(chrono.parse_age("two weeks after the wedding"), (2, 2, False))
        self.assertEqual(chrono.parse_age("1985"), (5, 5, False))
        reading = cc.temporal_reading(
            event("A day", "Something happened.", when_hint="two weeks after the wedding")
        )
        self.assertEqual(reading["claim_type"], "occurrence")
        _run(self.root, publish=False)
        letter = [
            row for row in ts.active_claims(ts.fold_active_index(self.root))
            if row.get("event_mention") == "Grandpa's two-page letter"
        ]
        self.assertEqual(len(letter), 1)
        self.assertEqual(letter[0]["claim_type"], "occurrence")
        self.assertIn("sixth grade", letter[0]["evidence"][0]["quote"])

    def test_a_year_in_the_age_field_is_not_an_age(self):
        reading = cc.temporal_reading(
            event("A day", "Something happened.",
                  date={"stated": None, "age": "1985", "anchor_ref": None,
                        "relation": None})
        )
        self.assertEqual(reading["claim_type"], "occurrence")

    def test_an_anchor_ref_becomes_an_ordering_claim_and_free_text_never_does(self):
        anchored = cc.temporal_reading(
            event("A day", "Something happened.",
                  anchor="the move to Mesa",
                  date={"stated": None, "age": None,
                        "anchor_ref": "the move to Mesa", "relation": "after"})
        )
        self.assertEqual(anchored["claim_type"], "relative_order")
        self.assertEqual(
            anchored["temporal_value"],
            {"relation": "after", "anchors": ["the move to Mesa"]},
        )
        bare = cc.temporal_reading(
            event("A day", "Something happened.",
                  date={"stated": None, "age": None,
                        "anchor_ref": "the wedding", "relation": None})
        )
        self.assertEqual(bare["temporal_value"]["relation"], "within")
        # The free-text `anchor` alone asserts nothing: "nearest" is not
        # "during", and inventing the relation would be a guess.
        self.assertEqual(
            cc.temporal_reading(
                event("A day", "Something happened.", anchor="the move to Mesa")
            )["claim_type"],
            "occurrence",
        )

    def test_two_undated_moments_in_one_story_are_two_claims(self):
        # The identity keys are FROZEN: two undated moments of one subject in
        # one source revision would derive ONE claim id. The per-event source
        # id is what keeps them two moments instead of one.
        root = _vault(self)
        relative = _story(root, "one-afternoon")
        _classification(root, "one-afternoon", classification(
            relative,
            event("The green bike", "There was a green bike."),
            event("The dog next door", "There was a dog next door."),
        ))
        _run(root, publish=False)
        rows = ts.active_claims(ts.fold_active_index(root))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["claim_id"] for row in rows}), 2)
        self.assertEqual(len({row["event_ref"] for row in rows}), 2)


# --------------------------------------------------------------------------
# 2 — idempotency, on the bytes
# --------------------------------------------------------------------------


class IdempotencyTests(unittest.TestCase):
    """§8.6 row 2. A second run writes nothing and publishes the same bytes."""

    def setUp(self):
        self.root = _vault(self)
        self.relative = _story(self.root, "the-move")
        _birth_receipt(self.root, self.relative)
        _classification(self.root, "the-move", classification(
            self.relative,
            event("The Williams house", "We moved into the Williams house.",
                  date={"stated": "1988", "age": None, "anchor_ref": None,
                        "relation": None}),
            event("The bike with no brakes", "I rode a bike with no brakes."),
        ))

    def test_a_second_run_is_a_byte_identical_no_op(self):
        first = _run(self.root)
        before = _files(self.root)
        second = _run(self.root)
        self.assertEqual(_files(self.root), before)
        self.assertEqual(second["claims"], first["claims"])
        self.assertEqual(second["receipts_written"], 0)

    def test_deleting_the_index_and_rebuilding_it_is_byte_identical(self):
        _run(self.root)
        index = ts.active_index_path(self.root).read_bytes()
        ts.active_index_path(self.root).unlink()
        ts.rebuild_active_index(self.root)
        self.assertEqual(ts.active_index_path(self.root).read_bytes(), index)

    def test_dry_run_writes_nothing(self):
        before = _files(self.root)
        report = cc.migrate_classifier_moments(
            self.root,
            classifications_dir=self.root / "state" / "classifications",
            dry_run=True,
            now=NOW,
        )
        self.assertEqual(_files(self.root), before)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["events"], 2)
        self.assertEqual(report["claims"], 2)
        self.assertEqual(report["nodes_after"], report["nodes_before"] + 2)
        self.assertIn("dry run", "\n".join(cc.describe_migration(report)))


# --------------------------------------------------------------------------
# 3 — the recorder is canonical
# --------------------------------------------------------------------------


class RecorderIsCanonicalTests(unittest.TestCase):
    """§8.6 row 3 (CLAUDE.md paradigm 9)."""

    def setUp(self):
        self.root = _vault(self)
        self.relative = _story(self.root, "born")
        _birth_receipt(self.root, self.relative)

    def test_a_classifier_event_over_a_recorded_date_is_not_re_minted(self):
        _classification(self.root, "born", classification(
            self.relative,
            event("Being born", "I was born in 1981.",
                  date={"stated": "1981", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        report = _run(self.root, publish=False)
        self.assertEqual(report["deduped_against_recorder"], 1)
        self.assertEqual(report["deduped_sources"], 1)
        self.assertEqual(report["claims"], 0)
        kinds = {
            row["extractor_version"]
            for row in ts.active_claims(ts.fold_active_index(self.root))
        }
        self.assertEqual(kinds, {"landmark_recorder/rule:1"})

    def test_an_undated_moment_from_the_same_source_still_lands(self):
        # The recorder is canonical for what it RECORDED. A moment nobody
        # recorded is not a rival to anything.
        _classification(self.root, "born", classification(
            self.relative,
            event("Being born", "I was born in 1981.",
                  date={"stated": "1981", "age": None, "anchor_ref": None,
                        "relation": None}),
            event("The hospital on the hill", "It was the hospital on the hill."),
        ))
        report = _run(self.root, publish=False)
        self.assertEqual(report["deduped_against_recorder"], 1)
        self.assertEqual(report["claims"], 1)
        self.assertEqual(report["claims_by_type"]["occurrence"], 1)

    def test_a_disjoint_date_from_the_same_source_is_kept_as_a_rival(self):
        _classification(self.root, "born", classification(
            self.relative,
            event("Being born", "I was born in 1990.",
                  date={"stated": "1990", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        report = _run(self.root, publish=False)
        self.assertEqual(report["deduped_against_recorder"], 0)
        self.assertEqual(report["claims"], 1)


# --------------------------------------------------------------------------
# 4 — somebody else's occurrence never rides on the owner's axis
# --------------------------------------------------------------------------


class SubjectScopeTests(unittest.TestCase):
    """§8.6 row 4; eras §5's two independent facts."""

    def setUp(self):
        self.root = _vault(self)
        self.relative = _story(self.root, "grandma")
        _birth_receipt(self.root, self.relative)
        self.roster = roster(person("Betty Jo"), person("Author"))

    def test_a_named_relatives_moment_is_other_person_and_off_the_axis(self):
        _classification(self.root, "grandma", classification(
            self.relative,
            event("Betty Jo's first winter", "Betty Jo spent that winter alone.",
                  subject="Betty Jo",
                  date={"stated": "1954", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        _run(self.root, publish=False)
        result = _fold(self.root, roster_snapshot=self.roster)
        node = next(
            row for row in result.nodes if row.get("label", "").startswith("Betty Jo")
        )
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertNotIn(node["owner_timeline_relation"], ("participated", "lived_effect"))

    def test_the_owners_own_moment_stays_on_the_axis(self):
        _classification(self.root, "grandma", classification(
            self.relative,
            event("The green bike", "I rode a green bike.",
                  date={"stated": "1989", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        _run(self.root, publish=False)
        result = _fold(self.root, roster_snapshot=self.roster)
        node = next(row for row in result.nodes if row.get("label") == "The green bike")
        self.assertEqual(node["occurrence_subject_scope"], "owner")
        self.assertEqual(node["owner_timeline_relation"], "participated")

    def test_a_document_level_person_never_moves_the_subject(self):
        # "A relative's unrelated history never rides in on a stated
        # relationship alone" — a person named in the STORY is not the actor
        # of every moment in it.
        _classification(self.root, "grandma", classification(
            self.relative,
            event("The green bike", "I rode a green bike."),
            people=[{"name": "Betty Jo", "relationship": "grandmother"}],
        ))
        _run(self.root, publish=False)
        rows = ts.active_claims(ts.fold_active_index(self.root))
        moment = [row for row in rows if row.get("event_mention") == "The green bike"]
        self.assertEqual(moment[0]["subject_mention"], cc.OWNER_SUBJECT_REF)

    def test_the_subject_mention_is_left_raw_for_the_one_resolver(self):
        self.assertEqual(
            cc.event_subject_mention(event("x", "y", subject="Betty Jo")), "Betty Jo"
        )
        self.assertEqual(cc.event_subject_mention(event("x", "y")), "self")
        # An enumerated subject is refused as a subject, never split here —
        # `validate_temporal_claim` owns that rule.
        self.assertEqual(
            cc.event_subject_mention(event("x", "y", subject="Ada, Bo and Cy")), "self"
        )


# --------------------------------------------------------------------------
# 5 — the occurrence claim type
# --------------------------------------------------------------------------


class OccurrenceClaimTests(unittest.TestCase):
    """§8.6 row 5 — the contract extension, and why it was needed."""

    def test_the_type_exists_and_carries_an_event_but_no_time(self):
        self.assertIn("occurrence", tc.CLAIM_TYPES)
        self.assertIn("occurrence", tc.DATELESS_CLAIM_TYPES)
        claim = tc.validate_temporal_claim(
            {
                "claim_type": "occurrence",
                "subject_mention": "self",
                "event_kind": "moment",
                "evidence": "There was a green bike.",
                "source_kind": "import",
                "source_ref": {"source_id": "classification:x#abc",
                               "revision": "sha256:" + "1" * 64},
                "extractor_version": cc.CLASSIFIER_EXTRACTOR,
            },
            now=NOW,
        )
        self.assertIsNone(claim["temporal_value"])
        self.assertEqual(claim["event_kind"], "moment")

    def test_an_occurrence_claim_with_a_date_is_refused_by_name(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                {
                    "claim_type": "occurrence",
                    "subject_mention": "self",
                    "event_kind": "moment",
                    "temporal_value": "1988",
                    "evidence": "x",
                    "source_kind": "import",
                    "source_ref": {"source_id": "classification:x#abc",
                                   "revision": "sha256:" + "1" * 64},
                    "extractor_version": cc.CLASSIFIER_EXTRACTOR,
                },
                now=NOW,
            )
        self.assertEqual(
            caught.exception.code, "occurrence_claim_carries_no_temporal_value"
        )

    def test_a_dated_type_with_no_value_is_still_refused(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.validate_temporal_claim(
                {
                    "claim_type": "date",
                    "subject_mention": "self",
                    "event_kind": "moment",
                    "evidence": "x",
                    "source_kind": "import",
                    "source_ref": {"source_id": "classification:x#abc",
                                   "revision": "sha256:" + "1" * 64},
                    "extractor_version": cc.CLASSIFIER_EXTRACTOR,
                },
                now=NOW,
            )
        self.assertEqual(caught.exception.code, "temporal_claim_needs_value")

    def test_a_model_extractor_is_never_offered_the_dateless_type(self):
        # Keeping the two vocabularies apart is what keeps every composed
        # recorder/listener prompt byte-identical across this release.
        self.assertNotIn("occurrence", tc.MODEL_CLAIM_TYPES)
        self.assertEqual(
            set(tc.CLAIM_TYPES) - set(tc.MODEL_CLAIM_TYPES), {"occurrence"}
        )

    def test_an_undated_moment_becomes_a_node_with_no_date(self):
        root = _vault(self)
        relative = _story(root, "the-bike")
        _birth_receipt(root, relative)
        _classification(root, "the-bike", classification(
            relative, event("The green bike", "There was a green bike."),
        ))
        _run(root, publish=False)
        result = _fold(root)
        node = next(row for row in result.nodes if row.get("label") == "The green bike")
        self.assertIsNone(node["best_temporal_value"])
        self.assertIsNone(node.get("possible_temporal_value"))
        self.assertIn(node["node_id"], result.diagnostics["unplaced"])

    def test_the_frames_still_carry_the_dated_ones(self):
        root = _vault(self)
        relative = _story(root, "childhood")
        _birth_receipt(root, relative)
        _classification(root, "childhood", classification(
            relative,
            event("The green bike", "I rode a green bike.",
                  date={"stated": "1989", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        _run(root, publish=False)
        result = _fold(root)
        node = next(row for row in result.nodes if row.get("label") == "The green bike")
        self.assertEqual(node["best_temporal_value"]["best"], "1989")
        self.assertEqual(node["basis"], "explicit")


# --------------------------------------------------------------------------
# Supersession — a re-classification never edits
# --------------------------------------------------------------------------


class ReclassificationTests(unittest.TestCase):
    """§8.1: "re-classification supersedes, never edits"."""

    def setUp(self):
        self.root = _vault(self)
        self.relative = _story(self.root, "the-move")
        _classification(self.root, "the-move", classification(
            self.relative,
            event("The Williams house", "We moved into the Williams house.",
                  date={"stated": "1988", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        _run(self.root, publish=False)
        self.first = ts.active_claims(ts.fold_active_index(self.root))[0]

    def test_a_corrected_date_supersedes_and_never_rewrites_the_receipt(self):
        _classification(self.root, "the-move", classification(
            self.relative,
            event("The Williams house", "We moved into the Williams house.",
                  date={"stated": "1989", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        report = _run(self.root, publish=False)
        self.assertEqual(report["superseded_claims"], 1)
        self.assertEqual(report["superseded_classifications"], 1)
        index = ts.fold_active_index(self.root)
        by_id = {row["claim_id"]: row for row in index["claims"]}
        self.assertEqual(by_id[self.first["claim_id"]]["status"], "superseded")
        active = ts.active_claims(index)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["temporal_value"]["best"], "1989")
        # The earlier receipt is untouched: history, not a cache.
        self.assertEqual(len(ts.load_receipts(self.root)[0]), 2)

    def test_superseding_the_same_reading_twice_files_one_correction(self):
        _classification(self.root, "the-move", classification(
            self.relative,
            event("The Williams house", "We moved into the Williams house.",
                  date={"stated": "1989", "age": None, "anchor_ref": None,
                        "relation": None}),
        ))
        _run(self.root, publish=False)
        before = _files(self.root)
        _run(self.root, publish=False)
        self.assertEqual(_files(self.root), before)
        self.assertEqual(len(ts.load_temporal_corrections(self.root)), 1)

    def test_an_event_deleted_by_re_classification_is_superseded_too(self):
        _classification(self.root, "the-move", classification(
            self.relative,
            event("A different memory entirely", "Something else happened."),
        ))
        _run(self.root, publish=False)
        index = ts.fold_active_index(self.root)
        by_id = {row["claim_id"]: row for row in index["claims"]}
        self.assertEqual(by_id[self.first["claim_id"]]["status"], "superseded")
        self.assertEqual(len(ts.active_claims(index)), 1)


# --------------------------------------------------------------------------
# Places, carried as evidence for the co-location rule
# --------------------------------------------------------------------------


class PlaceMentionTests(unittest.TestCase):
    """§8.1's `place_mentions`, and §8.0's finding that `load_events` drops them."""

    def test_the_documents_places_reach_the_claim(self):
        root = _vault(self)
        relative = _story(root, "san-diego")
        _classification(root, "san-diego", classification(
            relative,
            event("The Thunderhead street house", "We rented on Thunderhead street."),
            places=[{"name": "San Diego", "type": "city"},
                    {"name": "San Diego", "type": "city"}],
        ))
        _run(root, publish=False)
        row = ts.active_claims(ts.fold_active_index(root))[0]
        self.assertEqual(row["place_mentions"], ["San Diego"])

    def test_an_events_own_place_comes_first(self):
        self.assertEqual(
            cc.event_place_mentions(
                event("x", "y", places=["Mesa"]), [{"name": "Arizona"}]
            ),
            ("Mesa", "Arizona"),
        )

    def test_places_are_never_part_of_a_claims_identity(self):
        self.assertNotIn("place_mentions", tc.CLAIM_IDENTITY_KEYS)
        base = {
            "claim_type": "occurrence",
            "subject_mention": "self",
            "event_kind": "moment",
            "evidence": "x",
            "source_kind": "import",
            "source_ref": {"source_id": "classification:x#abc",
                           "revision": "sha256:" + "1" * 64},
            "extractor_version": cc.CLASSIFIER_EXTRACTOR,
        }
        bare = tc.validate_temporal_claim(dict(base), now=NOW)
        placed = tc.validate_temporal_claim(
            {**base, "place_mentions": ["Mesa"]}, now=NOW
        )
        self.assertEqual(bare["claim_id"], placed["claim_id"])
        self.assertNotIn("place_mentions", bare)

    def test_a_sentence_is_not_a_place(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            tc.normalized_place_mentions(["x" * (tc.MAX_PLACE_MENTION_CHARS + 1)])
        self.assertEqual(caught.exception.code, "place_mention_too_long")


# --------------------------------------------------------------------------
# The reader gate, and what the migration refuses to touch
# --------------------------------------------------------------------------


class MigrationBoundaryTests(unittest.TestCase):
    def test_a_stale_classification_is_withheld_exactly_as_everywhere_else(self):
        root = _vault(self)
        relative = _story(root, "stale")
        payload = classification(
            root and relative, event("The green bike", "There was a green bike."),
        )
        payload["stale"] = True
        _classification(root, "stale", payload)
        report = _run(root, publish=False)
        self.assertEqual(report["classifications"], 0)
        self.assertEqual(report["claims"], 0)

    def test_a_classification_whose_source_is_gone_is_named_not_dropped(self):
        root = _vault(self)
        _classification(root, "ghost", classification(
            "sources/stories/never-existed.md",
            event("The green bike", "There was a green bike."),
        ))
        report = _run(root, publish=False)
        self.assertEqual(report["skipped_source_missing"], ["ghost"])
        self.assertEqual(report["claims"], 0)

    def test_the_migration_never_edits_the_classifications(self):
        root = _vault(self)
        relative = _story(root, "the-move")
        path = _classification(root, "the-move", classification(
            relative, event("The green bike", "There was a green bike."),
        ))
        before = path.read_bytes()
        _run(root, publish=False)
        self.assertEqual(path.read_bytes(), before)

    def test_a_filing_step_never_redraws_the_landmark_projection(self):
        # CLAUDE.md's rule, learned on lifehug-platform#680.
        root = _vault(self)
        relative = _story(root, "the-move")
        _classification(root, "the-move", classification(
            relative, event("The green bike", "There was a green bike."),
        ))
        _run(root)
        self.assertFalse((root / "state" / "landmarks.json").exists())

    def test_only_the_named_source_runs_when_one_is_named(self):
        root = _vault(self)
        first = _story(root, "one")
        second = _story(root, "two")
        _classification(root, "one", classification(
            first, event("The green bike", "There was a green bike.")))
        _classification(root, "two", classification(
            second, event("The dog next door", "There was a dog next door.")))
        report = cc.migrate_classifier_moments(
            root,
            classifications_dir=root / "state" / "classifications",
            sources=[second],
            dry_run=False,
            publish=False,
            now=NOW,
        )
        self.assertEqual(report["events"], 1)
        rows = ts.active_claims(ts.fold_active_index(root))
        self.assertEqual([row["event_mention"] for row in rows], ["The dog next door"])


# --------------------------------------------------------------------------
# Publication — the whole point: one list, with the moments in it
# --------------------------------------------------------------------------


class PublicationTests(unittest.TestCase):
    def test_the_published_projection_holds_the_migrated_moments(self):
        root = _vault(self)
        relative = _story(root, "childhood")
        _birth_receipt(root, relative)
        _classification(root, "childhood", classification(
            relative,
            event("The green bike", "I rode a green bike.",
                  date={"stated": "1989", "age": None, "anchor_ref": None,
                        "relation": None}),
            event("The dog next door", "There was a dog next door."),
        ))
        report = _run(root)
        published = pub.read_projection(root)
        labels = {node["label"] for node in published["nodes"]}
        self.assertIn("The green bike", labels)
        self.assertIn("The dog next door", labels)
        self.assertEqual(report["nodes_after"], len(published["nodes"]))
        self.assertGreater(report["nodes_after"], report["nodes_before"])

    def test_publishing_twice_advances_nothing_semantic(self):
        root = _vault(self)
        relative = _story(root, "childhood")
        _birth_receipt(root, relative)
        _classification(root, "childhood", classification(
            relative, event("The green bike", "I rode a green bike.",
                            date={"stated": "1989", "age": None,
                                  "anchor_ref": None, "relation": None})))
        _run(root)
        first = pub.rebuild_signature(pub.read_projection(root))
        _run(root)
        self.assertEqual(pub.rebuild_signature(pub.read_projection(root)), first)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
