"""v375: a re-key is not a change to a life.

The owner's ruling, 2026-09-29: "A software re-key is not a change to my life;
carry links over." A node id is a hash of kind, subject WORDS and discriminator,
so a rule move that re-mints ids (v350's identity re-key, a roster word that
newly resolves) used to change the ``context_digest`` of every source that
could see the node, and the refresh sweep re-read stories nothing had changed.

All data is synthetic. The fixture is a shared context catalog in exactly the
shape ``classifier_context.load_context_catalog`` returns, so each re-key is
stated precisely: which ids moved, whether the projection published a
redirect, and whether anything the candidate MEANS moved with it.

``V374_DIGESTS`` were produced by running :func:`fixture_digests` against the
v374 builder (main at 9002b63) — the proof that releasing v375 moves no
digest of a source whose candidates were not re-keyed.
"""

from __future__ import annotations

import copy
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classifier_context as cc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import timeline_evidence as te  # noqa: E402

HOUSE = "place/elm-street-house"
ACME = "organization/acme"
SCHOOL = "organization/lincoln-high"
ROSTER_ALIASES = {
    HOUSE: ("Elm Street", "Elm Street house"),
    ACME: ("Acme", "Acme Corp"),
    SCHOOL: ("Lincoln High",),
}

#: (key, event kind, entity ref, the word the id is minted on BEFORE the
#: re-key, discriminator, start, end). Two stays at one house: only their
#: discriminator tells them apart.
STAYS = {
    "stay-1994": ("residence", HOUSE, "Elm Street", "1", "1994-06", "1995-06"),
    "stay-1998": ("residence", HOUSE, "Elm Street", "2", "1998-02", "1999-01"),
    "job": ("job", ACME, "Acme", "2001-03", "2001-03", "2004-08"),
    "school": ("school", SCHOOL, "Lincoln High", "1990-09", "1990-09", "1994-06"),
}

STORIES = {
    "moving": (
        "We moved into the Elm Street house in June 1994. The first winter "
        "there the pipes froze.\n",
        "Moved into the Elm Street house", "stay-1994",
        "We moved into the Elm Street house in June 1994",
    ),
    "work": (
        "I started at Acme in March 2001 as a junior analyst.\n",
        "Started at Acme", "job", "I started at Acme in March 2001",
    ),
    "track": (
        "At Lincoln High I ran track every spring.\n",
        "Ran track at Lincoln High", "school", "At Lincoln High I ran track",
    ),
}


def node_id(key: str, *, word: str | None = None, discriminator: str | None = None) -> str:
    kind, _ref, before, disc, _start, _end = STAYS[key]
    return tp.derive_node_id(node_kind="episode", event_kind=kind,
                             subject_refs=[word or before],
                             discriminator=discriminator or disc)


def candidate_row(key: str, candidate_id: str, *, start: str | None = None,
                  end: str | None = None, basis: str = "stated") -> dict:
    kind, ref, _before, _disc, first, last = STAYS[key]
    start, end = start or first, end or last
    terms = ROSTER_ALIASES[ref]
    row = {
        "candidate_id": candidate_id,
        "node_kind": "episode",
        "episode_id": f"episode:{key}",
        "kind": kind,
        "name": terms[-1],
        "aliases": sorted(terms),
        "canonical_roster_terms": [{"entity_ref": ref, "terms": list(terms)}],
        "entity_refs": [ref],
        "unresolved_entity_mentions": [],
        "entity_ref_ambiguities": [],
        "supported_bounds": {"best": f"{start}/{end}", "earliest": start,
                             "latest": end, "granularity": "month"},
        "temporal_shape": "interval",
        "basis": basis,
        "conflict_state": "none",
        "alternatives": [],
        "event_role": kind,
        "grounding_identity": [],
    }
    row["reference_keys"] = te.candidate_reference_keys(row)
    return row


def identity(key: str, *, discriminator: str | None = None) -> dict:
    kind, ref, _before, disc, start, _end = STAYS[key]
    return {"node_kind": "episode", "event_kind": kind, "identity_refs": [ref],
            "discriminators": sorted({discriminator or disc, start})}


class Fixture:
    """Three stories, four candidates, and the re-keys applied to them."""

    def build(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="lifehug-v375-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "sources/manual").mkdir(parents=True)
        self.sources = {}
        for name, (text, *_rest) in STORIES.items():
            path = self.root / "sources/manual" / f"{name}.md"
            path.write_text(f"---\ntitle: {name}\n---\n{text}")
            self.sources[name] = path
        # The drawing before any re-key: every id minted on its words.
        self.ids = {key: node_id(key) for key in STAYS}
        self.overrides: dict[str, dict] = {}
        self.discriminators: dict[str, str] = {}
        self.aliases: dict[str, str] = {}
        self.records: dict[str, dict] = {}
        for name in STORIES:
            self.records[self.relative(name)] = self.file(name)

    def relative(self, name: str) -> str:
        return self.sources[name].relative_to(self.root).as_posix()

    def catalog(self) -> dict:
        rows = [candidate_row(key, self.ids[key], **self.overrides.get(key, {}))
                for key in STAYS]
        return {
            "roster_aliases": ROSTER_ALIASES,
            "roster_matchers": tuple(
                (ref, term, re.compile(rf"(?<!\w){re.escape(term.casefold())}(?!\w)"))
                for ref, terms in ROSTER_ALIASES.items() for term in terms
            ),
            "claims_by_source": {},
            "classifier_claims": {},
            "identities_by_id": {},
            "human_identity_records": [],
            "human_tellings_by_source": {},
            "independent_manifest": {},
            "manifest": {},
            "correction_records": [],
            "classifications": copy.deepcopy(self.records),
            "retracted_paths": set(),
            "candidates": [(row, frozenset()) for row in rows],
            "baseline_candidates": {},
            "candidate_identity": {
                self.ids[key]: identity(key, discriminator=self.discriminators.get(key))
                for key in STAYS
            },
            "node_aliases": dict(self.aliases),
            "drawn_node_ids": frozenset(self.ids.values()),
        }

    def snapshot(self, name: str) -> dict:
        return cc.build_context_snapshot_from_catalog(
            self.root, self.sources[name], self.catalog())

    def file(self, name: str) -> dict:
        """A reading filed against today's catalog, linked to its node."""
        text, title, key, quote = STORIES[name]
        event = {
            "title": title, "description": text.strip(), "subject": "self",
            "places": [], "when_hint": None, "anchor": None, "date": None,
            "timeline_relation": {"relation": "within", "candidate_id": self.ids[key],
                                  "entity_refs": [STAYS[key][1]],
                                  "evidence": {"quote": quote}},
        }
        event["event_key"] = te.event_key(event)
        record = {"source_path": self.relative(name), "events": [event]}
        self.records[record["source_path"]] = record
        snapshot = self.snapshot(name)
        context = snapshot["event_contexts"][event["event_key"]]
        event["timeline_resolution"] = {
            "status": "linked", "candidate_ids": list(context["candidate_ids"]),
            "reason": "Linked when filed.",
        }
        record["classification_snapshot"] = cc.snapshot_metadata(snapshot)
        return record

    def reason(self, name: str) -> str | None:
        return cc.refresh_reason(self.snapshot(name), self.records[self.relative(name)])

    def pending(self) -> dict:
        with mock.patch.object(cc, "_load_context_catalog", return_value=self.catalog()):
            return cc.select_refresh_targets(
                self.root, list(self.sources.values()), limit=10,
                classifications=copy.deepcopy(self.records))

    # -- the re-keys ------------------------------------------------------

    def re_key(self, *keys: str, word: str = "ref", redirect: bool = True) -> None:
        """Mint ``keys`` on a new word (the entity ref, or ``word``); the
        projection publishes the redirect when ``redirect``."""
        for key in keys:
            old = self.ids[key]
            new = node_id(key, word=(STAYS[key][1] if word == "ref" else word),
                          discriminator=self.discriminators.get(key))
            self.ids[key] = new
            if redirect:
                # The fold re-derives the former id from the filed mention and
                # redirects it to today's (`_identity_rekeys`): the FIRST id.
                first = node_id(key)
                self.aliases = {k: v for k, v in self.aliases.items() if v != old}
                if first != new:
                    self.aliases[first] = new
                if old not in (first, new):
                    self.aliases[old] = new


def fixture_digests(case: Fixture) -> dict:
    """Every digest the fixture produces before and after a pure re-key of the
    two stays. Shared with the v374 run that produced ``V374_DIGESTS``."""
    digests = {}
    for name in STORIES:
        digests[f"{name}:stored"] = case.records[case.relative(name)][
            "classification_snapshot"]["context_digest"]
    case.re_key("stay-1994", "stay-1998")
    for name in STORIES:
        digests[f"{name}:after"] = case.snapshot(name)["context_digest"]
    return digests


#: Produced by the v374 builder (main at 9002b63) on exactly this fixture.
V374_DIGESTS = {
    "moving:after": "sha256:3bc65d8bdaf2a9a61c32149e56762cb21fce0547e1b2194b26e6caf6000aa3e2",
    "moving:stored": "sha256:4278a2e1a65de4999dadee32025ece404c0e0f1437e410d2afb94adc3d8c2365",
    "track:after": "sha256:0fe1a2d7733fca54385f78653936aefdf83d352c882dd5206eb1586a632d3a42",
    "track:stored": "sha256:0fe1a2d7733fca54385f78653936aefdf83d352c882dd5206eb1586a632d3a42",
    "work:after": "sha256:8ad60d65d9b5ad0791c96485e3e8f6786e2d0cb40ccb885cd3419069f3799e27",
    "work:stored": "sha256:8ad60d65d9b5ad0791c96485e3e8f6786e2d0cb40ccb885cd3419069f3799e27",
}


class NoReKeyIsByteIdenticalTests(Fixture, unittest.TestCase):
    """Releasing v375 moves no digest a re-key did not touch."""

    def setUp(self) -> None:
        self.build()

    def test_stored_digests_are_the_v374_digests(self) -> None:
        digests = fixture_digests(self)
        for name in STORIES:
            self.assertEqual(digests[f"{name}:stored"], V374_DIGESTS[f"{name}:stored"], name)

    def test_sources_the_re_key_did_not_touch_are_byte_identical(self) -> None:
        digests = fixture_digests(self)
        for name in ("work", "track"):
            self.assertEqual(digests[f"{name}:after"], V374_DIGESTS[f"{name}:after"], name)
            self.assertEqual(digests[f"{name}:after"], digests[f"{name}:stored"], name)

    def test_v374_read_the_re_keyed_story_as_changed_and_v375_does_not(self) -> None:
        digests = fixture_digests(self)
        self.assertNotEqual(V374_DIGESTS["moving:after"], V374_DIGESTS["moving:stored"])
        self.assertEqual(digests["moving:after"], digests["moving:stored"])

    def test_schema_and_versions_do_not_move(self) -> None:
        """A bump would make every stored snapshot `legacy_snapshot`/changed:
        the whole-vault refresh this release exists to avoid."""
        self.assertEqual(cc.CONTEXT_SCHEMA_VERSION, 1)
        self.assertEqual(cc.PROMPT_VERSION, "contextual-timeline:3")
        self.assertEqual(cc.EXTRACTOR_VERSION, "story-classifier:2")


class APureReKeyTests(Fixture, unittest.TestCase):
    """Ids move, the projection redirects them, nothing they mean moves."""

    def setUp(self) -> None:
        self.build()
        self.stored_link = self.ids["stay-1994"]
        self.re_key("stay-1994", "stay-1998")

    def test_the_ids_really_moved(self) -> None:
        self.assertNotEqual(self.ids["stay-1994"], self.stored_link)
        self.assertEqual(self.aliases[self.stored_link], self.ids["stay-1994"])

    def test_digest_unchanged_links_carried_zero_pending(self) -> None:
        snapshot = self.snapshot("moving")
        record = self.records[self.relative("moving")]
        self.assertEqual(snapshot["context_digest"],
                         record["classification_snapshot"]["context_digest"])
        self.assertEqual(snapshot[cc.LINK_ORPHANED_FIELD], [])
        self.assertIsNone(cc.refresh_reason(snapshot, record))
        # The link is carried: the stored id walks to today's node, which is
        # the redirect the fold follows (timeline-rules:26).
        self.assertEqual(
            cc.walk_node_alias(self.stored_link, self.aliases, set(self.ids.values())),
            self.ids["stay-1994"])
        # ... and the carried node is in the event's own context.
        context = next(iter(snapshot["event_contexts"].values()))
        self.assertIn(self.ids["stay-1994"], context["candidate_ids"])
        report = self.pending()
        self.assertEqual(report["pending_count"], 0, report["targets"])

    def test_stable_across_a_second_re_key(self) -> None:
        first = self.snapshot("moving")["context_digest"]
        self.re_key("stay-1994", "stay-1998", word="the Elm Street place")
        self.assertNotIn(self.stored_link, self.ids.values())
        second = self.snapshot("moving")
        self.assertEqual(second["context_digest"], first)
        self.assertIsNone(cc.refresh_reason(second, self.records[self.relative("moving")]))
        self.assertEqual(self.pending()["pending_count"], 0)

    def test_the_prompt_still_reads_todays_ids(self) -> None:
        """Only the digest names candidates by their filed id."""
        snapshot = self.snapshot("moving")
        self.assertEqual({row["candidate_id"] for row in snapshot["candidates"]},
                         {self.ids["stay-1994"], self.ids["stay-1998"]})

    def test_a_re_key_that_also_changes_meaning_is_still_a_change(self) -> None:
        """The known risk, contained: a digested field that moves under a moved
        id (here the basis the stay is known on) still refreshes the story."""
        self.overrides["stay-1994"] = {"basis": "inferred"}
        self.assertEqual(self.reason("moving"), "context_changed")

    def test_bounds_were_never_in_the_digest(self) -> None:
        """Recorded, not changed: `supported_bounds` left the event-context
        fingerprint in 7f4d748 (2026-09-17), before v375, with or without a
        re-key. v375 neither adds nor drops a digested field."""
        self.overrides["stay-1994"] = {"start": "1994-08"}
        self.assertIsNone(self.reason("moving"))


class AProofOnlyReKeyTests(Fixture, unittest.TestCase):
    """No redirect: the old id recomputes from the candidate's identity."""

    def setUp(self) -> None:
        self.build()
        self.stored_link = self.ids["school"]
        self.re_key("school", redirect=False)

    def test_the_digest_is_unchanged(self) -> None:
        snapshot = self.snapshot("track")
        self.assertEqual(snapshot["context_digest"],
                         self.records[self.relative("track")]["classification_snapshot"][
                             "context_digest"])

    def test_the_link_the_fold_cannot_follow_is_link_orphaned_and_settles_by_rule(self) -> None:
        import timeline_settlement as ts  # noqa: PLC0415

        snapshot = self.snapshot("track")
        record = self.records[self.relative("track")]
        self.assertEqual(snapshot[cc.LINK_ORPHANED_FIELD],
                         [{"event_key": record["events"][0]["event_key"],
                           "candidate_id": self.stored_link}])
        self.assertEqual(cc.refresh_reason(snapshot, record), cc.LINK_ORPHANED)
        report = self.pending()
        self.assertEqual([(row["source_path"], row["reason"], row["settle"])
                          for row in report["targets"]],
                         [("sources/manual/track.md", cc.LINK_ORPHANED, "rule")])
        story = STORIES["track"][0]
        settled = ts.settle(snapshot, record, story)
        self.assertEqual(settled["judgment_keys"], [])
        delta = next(iter(settled["deltas"].values()))
        self.assertEqual(delta["timeline_relation"]["candidate_id"], self.ids["school"])
        self.assertEqual(delta["timeline_relation"]["remapped_from"], self.stored_link)

        # Filed as a timeline refresh stamps it: current, and nothing pending.
        event = record["events"][0]
        event["timeline_relation"] = delta["timeline_relation"]
        event["timeline_resolution"] = delta["timeline_resolution"]
        record["classification_snapshot"] = cc.snapshot_metadata_after_timeline_refile(snapshot)
        self.assertIsNone(self.reason("track"))
        self.assertEqual(self.pending()["pending_count"], 0)


class SwappedDiscriminatorsTests(Fixture, unittest.TestCase):
    """Two stays at one house, re-keyed AND re-ordered: never a silent swap."""

    def setUp(self) -> None:
        self.build()
        self.stored_link = self.ids["stay-1994"]
        self.discriminators = {"stay-1994": "2", "stay-1998": "1"}
        self.re_key("stay-1994", "stay-1998", redirect=False)

    def test_it_is_pending_with_the_honest_reason(self) -> None:
        snapshot = self.snapshot("moving")
        record = self.records[self.relative("moving")]
        self.assertNotEqual(snapshot["context_digest"],
                            record["classification_snapshot"]["context_digest"])
        self.assertEqual(cc.refresh_reason(snapshot, record), cc.LINK_ORPHANED)

    def test_no_rule_re_points_the_link_at_the_other_stay(self) -> None:
        """v373's recomputation alone would pick the 1998 stay: its new
        discriminator is the one the 1994 stay was minted with."""
        import timeline_settlement as ts  # noqa: PLC0415

        self.assertTrue(cc.identity_recomputes(
            self.stored_link, identity("stay-1998", discriminator="1"),
            ["Elm Street"]))
        snapshot = self.snapshot("moving")
        settled = ts.settle(snapshot, self.records[self.relative("moving")],
                            STORIES["moving"][0])
        self.assertEqual(settled["deltas"], {})
        self.assertEqual(len(settled["judgment_keys"]), 1)
        report = self.pending()
        self.assertEqual([(row["reason"], row["settle"]) for row in report["targets"]],
                         [(cc.LINK_ORPHANED, "model")])


class TheFoldFollowsTheRedirectTests(unittest.TestCase):
    """timeline-rules:26: a stored link to a re-keyed node keeps its edge."""

    def setUp(self) -> None:
        import temporal_timeline as tt  # noqa: PLC0415
        from test_v340_apply_keeps_placements import claim  # noqa: PLC0415
        from test_v350_one_couple_one_alias_one_label import (  # noqa: PLC0415
            ROSTER, derive, dad_graduated)

        self.tt = tt
        self.derive, self.roster = derive, ROSTER
        self.old_id = derive([dad_graduated()]).nodes[0]["node_id"]
        self.claims = [dad_graduated(), claim(
            claim_type="relative_order", subject_mention="the graduation party",
            event_kind="event", source="classification:party#0001",
            temporal_value={"relation": "after", "anchors": [self.old_id]},
            quote="the party after Dad graduated")]

    def unresolved(self, result) -> list:
        return [row for row in result.diagnostics["findings"]
                if row.get("finding") == "anchor_unresolved"
                and self.old_id in (row.get("anchors") or ())]

    def test_the_anchor_follows_the_alias(self) -> None:
        after = self.derive(self.claims, roster=self.roster)
        self.assertIn(self.old_id, after.node_aliases)
        self.assertEqual(self.unresolved(after), [])

    def test_without_the_rule_it_stood_unresolved(self) -> None:
        with mock.patch.object(self.tt, "_follow_node_alias", return_value=""):
            after = self.derive(self.claims, roster=self.roster)
        self.assertTrue(self.unresolved(after))

    def test_the_rule_version_moved(self) -> None:
        self.assertEqual(self.tt.CALCULATION_RULE_VERSION, "timeline-rules:26")
        self.assertIn("node_aliases", self.tt.A_LINK_FOLLOWS_ITS_NODE_THROUGH_A_RE_KEY)


class TheRuleIsWrittenDownTests(unittest.TestCase):
    def test_the_constant(self) -> None:
        text = cc.A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE
        self.assertIn("software re-key is not a change to a life", text)
        self.assertIn("link_orphaned", text)

    def test_link_orphaned_ranks_between_new_words_and_the_ambient_context(self) -> None:
        rank = cc.REFRESH_REASON_PRIORITY
        self.assertLess(rank["source_changed"], rank[cc.LINK_ORPHANED])
        self.assertLess(rank[cc.LINK_ORPHANED], rank["context_changed"])
        self.assertLess(rank["relationship_changed"], rank["context_changed"])

    def test_link_orphaned_is_a_timeline_refresh(self) -> None:
        import classify_story as cs  # noqa: PLC0415
        import timeline_settlement as ts  # noqa: PLC0415

        self.assertIn(cc.LINK_ORPHANED, ts.TIMELINE_REFRESH_REASONS)
        with mock.patch.object(cc, "refresh_reason", return_value=cc.LINK_ORPHANED):
            self.assertEqual(cs.classification_mode({}, {"events": []}), "timeline")

    def test_the_docs_travel_with_the_concept(self) -> None:
        spec = (ROOT / "docs/pr-specs/classifier-independent-context.md").read_text()
        self.assertIn("Amendment 2026-09-29 — a re-key is not a change to a life", spec)
        self.assertIn("machine manifest rekeys", spec)
        adr = (ROOT / "docs/adr/0039-a-re-key-is-not-a-change-to-a-life.md").read_text()
        self.assertIn("Status: ratified (owner, 2026-09-29)", adr)
        self.assertIn("How to tell if a bug traces back here", adr)
        self.assertIn("A_RE_KEYED_LINK_REMAPS_BY_IDENTITY", adr)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("link_orphaned", readme)


if __name__ == "__main__":
    unittest.main()
