"""O-E3 — an era is an identity: era-record, the binder, and the era stage.

Contract: `docs/pr-specs/eras-o-e3-era-record.md`. Controlling design:
lifehug-platform `docs/design/eras.md` §2.3, §2.4, §4.1-4.5, §5.4, §7, §9.1.
Test ids are §9.1's (T-NE-*, T-W-*, T-B-*, T-CV-13).

Every negative test here was run against the unmodified base revision first
and SEEN failing; the evidence is in the PR body.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import era_identity as ei  # noqa: E402
import era_record as er  # noqa: E402
import event_binding as eb  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-27T12:00:00Z"


def _vault(case: unittest.TestCase) -> Path:
    root = root_parent_tmp(case, ROOT, prefix="eras-e3-")
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


# --------------------------------------------------------------------------
# S1 — identity, label, kind
# --------------------------------------------------------------------------


class EraIdentityTests(unittest.TestCase):
    """§2.3/§4.1 — the id is the creating act, never the label."""

    def test_the_id_is_the_operation_not_the_label(self):
        # T-NE-02. Two eras created in two different turns with the SAME name
        # are two eras; one era renamed is still one era. Both halves of that
        # are this one property.
        first = ei.era_id_for(ei.turn_operation_id("s1", "t1"))
        second = ei.era_id_for(ei.turn_operation_id("s1", "t2"))
        self.assertNotEqual(first, second)
        self.assertEqual(first, ei.era_id_for("s1#t1"))
        self.assertTrue(first.startswith("era:"))

    def test_the_migration_id_is_the_batch_and_the_slug(self):
        self.assertEqual(
            ei.migration_operation_id("1", "the-mission"), "migration:1:the-mission"
        )
        self.assertEqual(
            ei.era_id_for("migration:1:the-mission"),
            ei.era_id_for(ei.migration_operation_id("1", "the-mission")),
        )

    def test_an_operation_id_is_required(self):
        with self.assertRaises(ei.EraIdentityError) as caught:
            ei.era_id_for("")
        self.assertEqual(caught.exception.code, "era_operation_id_required")

    def test_no_mutable_label_is_inside_identity(self):
        # The identity record's own frontmatter must not carry the label:
        # design §2.3, "no mutable label inside identity".
        root = _vault(self)
        record, created = ei.file_era_identity(
            root, operation_id="s1#t1", era_kind="stretch",
            label_hint="College Years", occurred_at=NOW,
        )
        self.assertTrue(created)
        self.assertNotIn("label", record)
        self.assertEqual(record["era_id"], ei.era_id_for("s1#t1"))
        self.assertEqual(record["origin"], "person")
        self.assertEqual(record["creation_operation_id"], "s1#t1")

    def test_filing_the_same_identity_twice_writes_nothing(self):
        # T-W-01. Replay is a no-op at the identity step.
        root = _vault(self)
        ei.file_era_identity(root, operation_id="s1#t1", occurred_at=NOW)
        before = _files(root)
        _record, created = ei.file_era_identity(
            root, operation_id="s1#t1", occurred_at="2026-09-01T00:00:00Z",
            label_hint="a different hint entirely",
        )
        self.assertFalse(created)
        self.assertEqual(before, _files(root))

    def test_an_unknown_origin_and_an_unknown_kind_are_refused(self):
        root = _vault(self)
        with self.assertRaises(ei.EraIdentityError) as origin:
            ei.file_era_identity(root, operation_id="s1#t1", origin="vibes")
        self.assertEqual(origin.exception.code, "era_origin_unknown")
        with self.assertRaises(ei.EraIdentityError) as kind:
            ei.file_era_identity(root, operation_id="s1#t1", era_kind="chapter")
        self.assertEqual(kind.exception.code, "era_kind_unknown")


class EraLabelTests(unittest.TestCase):
    """§4.1 — the label is a decision on the id, and renaming keeps the id."""

    def setUp(self):
        self.root = _vault(self)
        self.era_id = ei.era_id_for("s1#t1")
        ei.file_era_identity(self.root, operation_id="s1#t1", era_kind="stretch",
                             occurred_at=NOW, label_hint="College Years")

    def test_a_label_names_an_era_and_reads_back(self):
        record, created = ei.file_era_label(
            self.root, era_id=self.era_id, label="College Years",
            aliases=["College", "school years"], occurred_at=NOW,
        )
        self.assertTrue(created)
        view = ei.era_views(self.root)[self.era_id]
        self.assertEqual(view["label"], "College Years")
        self.assertEqual(view["aliases"], ["College", "school years"])
        self.assertEqual(view["era_kind"], "stretch")
        self.assertEqual(record["era_id"], self.era_id)

    def test_rename_preserves_the_era_id_and_keeps_both_records(self):
        # T-NE-17. The whole reason identity is opaque.
        first, _ = ei.file_era_label(self.root, era_id=self.era_id,
                                     label="College Years", aliases=["College"],
                                     occurred_at=NOW)
        digest = ei._digest_of(first)
        second, _ = ei.file_era_label(
            self.root, era_id=self.era_id, label="Finding My Direction",
            aliases=["College"], supersedes=digest,
            occurred_at="2026-09-01T00:00:00Z",
        )
        views = ei.era_views(self.root)
        self.assertEqual(list(views), [self.era_id])
        self.assertEqual(views[self.era_id]["label"], "Finding My Direction")
        # Both label records survive; the old name is still readable.
        labels = ei.load_era_labels(self.root)
        self.assertEqual({row["label"] for row in labels},
                         {"College Years", "Finding My Direction"})
        self.assertEqual(second["supersedes"], digest)

    def test_the_same_label_decision_filed_twice_writes_nothing(self):
        ei.file_era_label(self.root, era_id=self.era_id, label="College Years",
                          aliases=["College"], occurred_at=NOW)
        before = _files(self.root)
        _record, created = ei.file_era_label(
            self.root, era_id=self.era_id, label="College Years",
            aliases=["College"], occurred_at="2026-09-09T00:00:00Z",
        )
        self.assertFalse(created)
        self.assertEqual(before, _files(self.root))

    def test_aliases_are_deduplicated_by_the_one_normalization(self):
        ei.file_era_label(self.root, era_id=self.era_id, label="The Mission",
                          aliases=["the mission", "The  Mission", "Mission"],
                          occurred_at=NOW)
        view = ei.era_views(self.root)[self.era_id]
        self.assertEqual(len(view["aliases"]), 2)

    def test_an_empty_label_is_refused(self):
        with self.assertRaises(ei.EraIdentityError) as caught:
            ei.file_era_label(self.root, era_id=self.era_id, label="  ")
        self.assertEqual(caught.exception.code, "era_label_required")

    def test_label_index_keeps_both_eras_that_share_an_alias(self):
        # The property the binder's correctness rests on: two candidates are
        # never collapsed to one.
        ei.file_era_label(self.root, era_id=self.era_id, label="The Mission",
                          occurred_at=NOW)
        other = ei.era_id_for("s2#t9")
        ei.file_era_identity(self.root, operation_id="s2#t9", occurred_at=NOW)
        ei.file_era_label(self.root, era_id=other, label="Mission Years",
                          aliases=["the mission"], occurred_at=NOW)
        index = ei.label_index(ei.era_views(self.root))
        self.assertEqual(index["the mission"], tuple(sorted([self.era_id, other])))


class EraKindTests(unittest.TestCase):
    """§4.5 — stretch or thread, decided at creation, flipped by a record."""

    def setUp(self):
        self.root = _vault(self)
        self.era_id = ei.era_id_for("s1#t1")
        ei.file_era_identity(self.root, operation_id="s1#t1", occurred_at=NOW)

    def test_the_newest_active_kind_is_the_one_that_counts(self):
        first, _ = ei.file_era_kind(self.root, era_id=self.era_id,
                                    era_kind="stretch", occurred_at=NOW)
        ei.file_era_kind(self.root, era_id=self.era_id, era_kind="thread",
                         supersedes=ei._digest_of(first),
                         occurred_at="2026-09-01T00:00:00Z")
        self.assertEqual(ei.era_views(self.root)[self.era_id]["era_kind"], "thread")
        self.assertEqual(len(ei.load_era_kinds(self.root)), 2)

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ei.EraIdentityError) as caught:
            ei.file_era_kind(self.root, era_id=self.era_id, era_kind="chapter")
        self.assertEqual(caught.exception.code, "era_kind_unknown")


class EraRecordDriftTests(unittest.TestCase):
    """A record whose body drifted under the decisions citing it is a failure."""

    def test_a_drifted_body_is_named_not_shrugged_at(self):
        root = _vault(self)
        record, _ = ei.file_era_identity(root, operation_id="s1#t1", occurred_at=NOW)
        path = root / record["relative_path"]
        path.write_text(path.read_text() + "\nsomebody edited this\n", encoding="utf-8")
        with self.assertRaises(ei.EraIdentityError) as caught:
            ei.read_era_record(root, record["relative_path"])
        self.assertEqual(caught.exception.code, "era_record_unreadable")


# --------------------------------------------------------------------------
# S2 — migration
# --------------------------------------------------------------------------

LEGACY_ROSTER = [
    {
        "type": "period",
        "entities": [
            {"slug": "the-mission", "name": "The Mission", "page_eligible": True,
             "aliases": ["Mission"], "chrono": {"best": "2001"}},
            {"slug": "college", "name": "College", "page_eligible": True},
            {"slug": "my-20s", "name": "My 20s", "page_eligible": True},
            {"slug": "quiet-years", "name": "Quiet Years", "page_eligible": False},
            {"slug": "", "name": "Nameless", "page_eligible": True},
            {"slug": "college-years", "name": "college", "page_eligible": True},
        ],
    }
]


class MigrationTests(unittest.TestCase):
    """§4.1 — one identity + one label per page_eligible non-age period."""

    def test_the_dry_run_writes_nothing_and_says_everything(self):
        root = _vault(self)
        before = _files(root)
        report = ei.migrate_legacy_periods(
            root, roster_snapshot=LEGACY_ROSTER, batch="1", dry_run=True, now=NOW
        )
        self.assertEqual(before, _files(root))
        self.assertEqual(
            sorted(report["mapped"]), ["college", "college-years", "the-mission"]
        )
        self.assertEqual(report["skipped_age_bands"], ["my-20s"])
        self.assertEqual(report["skipped_not_page_eligible"], ["quiet-years"])
        self.assertEqual(report["orphans"], ["Nameless"])
        self.assertEqual(report["unsupported_legacy_dates"]["the-mission"], ["chrono"])
        self.assertEqual(report["duplicates"]["college"],
                         ["college", "college-years"])

    def test_migrating_files_one_identity_and_one_label_each(self):
        root = _vault(self)
        report = ei.migrate_legacy_periods(
            root, roster_snapshot=LEGACY_ROSTER, batch="1", dry_run=False, now=NOW
        )
        self.assertEqual(report["created_identities"], 3)
        self.assertEqual(report["created_labels"], 3)
        views = ei.era_views(root)
        self.assertEqual(len(views), 3)
        mission = views[report["mapped"]["the-mission"]]
        self.assertEqual(mission["origin"], "legacy_roster")
        self.assertEqual(mission["legacy_slug"], "the-mission")
        self.assertEqual(mission["label"], "The Mission")
        self.assertEqual(mission["aliases"], ["Mission"])

    def test_no_roster_date_becomes_an_era_bound(self):
        # §4.1 — the roster's own `chrono` is reported and never filed. There
        # is no claim, no constraint, and nothing in the era's records that
        # could be read as a date.
        root = _vault(self)
        report = ei.migrate_legacy_periods(root, roster_snapshot=LEGACY_ROSTER,
                                           batch="1", dry_run=False, now=NOW)
        blob = "\n".join(
            (root / relative).read_text(encoding="utf-8")
            for relative in sorted(_files(root))
            if relative.startswith("sources/eras/")
        )
        self.assertNotIn("2001", blob)
        # The only claims a migration files are the eras' own IDENTITY claims
        # — no date, no event, nothing that could become a bound.
        index = ts.rebuild_active_index(root)
        kinds = {row["claim_type"] for row in ts.active_claims(index)}
        self.assertEqual(kinds, {"identity"})
        self.assertEqual(
            len(ts.active_claims(index)), len(report["mapped"]),
            "one identity claim per migrated era and not one more",
        )

    def test_rerunning_the_same_batch_writes_nothing(self):
        root = _vault(self)
        ei.migrate_legacy_periods(root, roster_snapshot=LEGACY_ROSTER,
                                  batch="1", dry_run=False, now=NOW)
        before = _files(root)
        again = ei.migrate_legacy_periods(
            root, roster_snapshot=LEGACY_ROSTER, batch="1", dry_run=False,
            now="2026-10-01T00:00:00Z",
        )
        self.assertEqual(again["created_identities"], 0)
        self.assertEqual(again["created_labels"], 0)
        self.assertEqual(before, _files(root))

    def test_a_different_batch_is_a_different_act(self):
        root = _vault(self)
        one = ei.migrate_legacy_periods(root, roster_snapshot=LEGACY_ROSTER,
                                        batch="1", dry_run=True)
        two = ei.migrate_legacy_periods(root, roster_snapshot=LEGACY_ROSTER,
                                        batch="2", dry_run=True)
        self.assertNotEqual(one["mapped"]["college"], two["mapped"]["college"])


# --------------------------------------------------------------------------
# S3 — event_mention, the binder, the resolution record
# --------------------------------------------------------------------------


def _claim(**overrides) -> dict:
    row = {
        "claim_type": "date",
        "subject_mention": "me",
        "event_kind": "period_started",
        "event_mention": "College",
        "temporal_value": "2007",
        "evidence": "2007 through 2011 as my College years",
        "source_kind": "conversation",
        "source_ref": {"source_id": "conversation:msg-1", "revision": "sha256:" + "1" * 64},
        "extractor_version": "landmark_recorder@1",
    }
    row.update(overrides)
    return tc.validate_temporal_claim(row, now=NOW)


class EventMentionContractTests(unittest.TestCase):
    """§4.3 — the ear writes the NAME; nothing in the prompt writes a link."""

    def test_the_leaf_may_emit_a_mention(self):
        import general_listener as gl  # noqa: PLC0415

        self.assertIn("event_mention", gl.CLAIM_PROMPT_KEYS)
        self.assertIn("event_mention", gl.CLAIM_DRAFT_KEYS)

    def test_the_leaf_may_not_emit_a_ref(self):
        # ADR 0029 is amended by exactly one key and not two.
        import general_listener as gl  # noqa: PLC0415

        self.assertNotIn("event_ref", gl.CLAIM_PROMPT_KEYS)
        self.assertNotIn("subject_ref", gl.CLAIM_PROMPT_KEYS)
        draft, finding = gl.validate_claim_draft({
            "claim_type": "date", "subject_mention": "me", "event_kind": "job",
            "event_ref": "era:1", "temporal_value": "1974", "evidence": "q",
        })
        self.assertIsNone(draft)
        self.assertEqual(finding, gl.claim_refused(gl.CLAIM_UNKNOWN_KEY))

    def test_both_leaves_teach_the_mention(self):
        for leaf in ("recorder.md", "listener.md"):
            text = (ROOT / "interactions" / "landmarks" / "prompt" / leaf).read_text()
            with self.subTest(leaf=leaf):
                self.assertIn("`event_mention` is what THEY called", text)
                self.assertNotIn("event_ref", text)

    def test_a_mention_survives_filing_and_is_not_in_the_id(self):
        with_mention = _claim()
        without = _claim(event_mention=None)
        self.assertEqual(with_mention["event_mention"], "College")
        self.assertNotIn("event_mention", without)
        # CLAIM_IDENTITY_KEYS is unchanged (design §2.3): a mention is data
        # about a claim, so the same fact keeps one id whether or not the ear
        # caught the name.
        self.assertEqual(with_mention["claim_id"], without["claim_id"])
        self.assertNotIn("event_mention", tc.CLAIM_IDENTITY_KEYS)

    def test_an_identity_claim_carries_no_mention(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            _claim(claim_type="identity", event_kind=None, temporal_value=None,
                   event_mention="College")
        self.assertEqual(caught.exception.code, "identity_claim_carries_no_event")

    def test_a_mention_that_is_a_paragraph_is_refused(self):
        with self.assertRaises(tc.TemporalClaimError) as caught:
            _claim(event_mention="x" * (tc.MAX_EVENT_MENTION_CHARS + 1))
        self.assertEqual(caught.exception.code, "event_mention_too_long")


class BinderTests(unittest.TestCase):
    """§4.3 — exact, whole-label, and a miss rather than a guess."""

    def setUp(self):
        self.root = _vault(self)
        self.college = ei.era_id_for("s1#t1")
        ei.file_era_identity(self.root, operation_id="s1#t1", occurred_at=NOW)
        ei.file_era_label(self.root, era_id=self.college, label="College Years",
                          aliases=["College"], occurred_at=NOW)
        self.index = ei.label_index(ei.era_views(self.root))

    def test_an_exact_case_folded_whole_label_binds(self):
        # T-B-01.
        for said in ("College", "college", "  COLLEGE  ", "College Years"):
            with self.subTest(said=said):
                ref, how, _ = eb.bind_event_mention(said, index=self.index)
                self.assertEqual(ref, self.college)
                self.assertEqual(how, "alias")

    def test_a_substring_never_binds(self):
        # "whole-label" is the whole rule: "college applications" is not
        # "College", and guessing that it is would be the wrong link §4.3
        # ranks above a miss.
        ref, how, candidates = eb.bind_event_mention(
            "college applications", index=self.index
        )
        self.assertIsNone(ref)
        self.assertEqual(how, "none")
        self.assertEqual(candidates, ())

    def test_the_target_wins_only_on_its_own_exact_label(self):
        # T-B-02. A session about the Mission does not capture a sentence
        # that named College.
        other = ei.era_id_for("s9#t9")
        ei.file_era_identity(self.root, operation_id="s9#t9", occurred_at=NOW)
        ei.file_era_label(self.root, era_id=other, label="The Mission", occurred_at=NOW)
        index = ei.label_index(ei.era_views(self.root))
        ref, how, _ = eb.bind_event_mention("College", index=index, target_era_id=other)
        self.assertEqual(ref, self.college)
        self.assertEqual(how, "alias")
        ref, how, _ = eb.bind_event_mention(
            "The Mission", index=index, target_era_id=other
        )
        self.assertEqual(ref, other)
        self.assertEqual(how, "target")

    def test_two_eras_sharing_an_alias_bind_to_neither(self):
        # The founder-shaped case: two eras aliased "the Mission".
        first = ei.era_id_for("s2#t1")
        second = ei.era_id_for("s3#t1")
        for era_id, op, label in ((first, "s2#t1", "The Mission"),
                                  (second, "s3#t1", "Mission Years")):
            ei.file_era_identity(self.root, operation_id=op, occurred_at=NOW)
            ei.file_era_label(self.root, era_id=era_id, label=label,
                              aliases=["the Mission"], occurred_at=NOW)
        index = ei.label_index(ei.era_views(self.root))
        ref, how, candidates = eb.bind_event_mention("the Mission", index=index)
        self.assertIsNone(ref)
        self.assertEqual(how, "none")
        self.assertEqual(set(candidates), {first, second})
        item = eb.ambiguous_work_item("the Mission", candidates,
                                      views=ei.era_views(self.root))
        self.assertEqual(item["kind"], eb.AMBIGUOUS_WORK_ITEM_KIND)
        self.assertEqual({row["ref"] for row in item["candidates"]}, {first, second})
        self.assertIn("The Mission", item["headline"])
        self.assertIn("Mission Years", item["headline"])

    def test_the_target_does_not_break_a_tie_it_is_not_in(self):
        first, second = ei.era_id_for("s2#t1"), ei.era_id_for("s3#t1")
        for era_id, op in ((first, "s2#t1"), (second, "s3#t1")):
            ei.file_era_identity(self.root, operation_id=op, occurred_at=NOW)
            ei.file_era_label(self.root, era_id=era_id, label=f"Era {op}",
                              aliases=["the Mission"], occurred_at=NOW)
        index = ei.label_index(ei.era_views(self.root))
        ref, _how, _ = eb.bind_event_mention(
            "the Mission", index=index, target_era_id=self.college
        )
        self.assertIsNone(ref)


class ResolutionRecordTests(unittest.TestCase):
    """§4.3 — the link is a record, and the claim is never edited."""

    def setUp(self):
        self.root = _vault(self)
        self.era_id = ei.era_id_for("s1#t1")

    def test_filing_a_resolution_twice_writes_one_file(self):
        record, created = eb.file_event_resolution(
            self.root, claim_id="claim:abc", event_mention="College",
            event_ref=self.era_id, bound_by="alias", now=NOW,
        )
        self.assertTrue(created)
        before = _files(self.root)
        again, made = eb.file_event_resolution(
            self.root, claim_id="claim:abc", event_mention="College",
            event_ref=self.era_id, bound_by="alias",
            now="2026-09-09T00:00:00Z",
        )
        self.assertFalse(made)
        self.assertEqual(again["resolution_id"], record["resolution_id"])
        self.assertEqual(before, _files(self.root))

    def test_a_miss_is_recorded_too(self):
        record, _ = eb.file_event_resolution(
            self.root, claim_id="claim:abc", event_mention="Narnia",
            bound_by="none", now=NOW,
        )
        self.assertIsNone(record["event_ref"])
        self.assertEqual(record["bound_by"], "none")
        self.assertIsNotNone(eb.read_event_resolution(self.root, record["relative_path"]))

    def test_the_fold_takes_the_newest_active_resolution(self):
        first = eb.validate_event_resolution({
            "claim_id": "claim:abc", "event_mention": "College",
            "event_ref": "era:aaa", "bound_by": "alias", "created_at": NOW,
        })
        second = eb.validate_event_resolution({
            "claim_id": "claim:abc", "event_mention": "College",
            "event_ref": "era:bbb", "bound_by": "target",
            "supersedes": first["resolution_id"],
            "created_at": "2026-09-01T00:00:00Z",
        })
        for order in ([first, second], [second, first]):
            with self.subTest(order=[r["event_ref"] for r in order]):
                index = eb.event_resolution_index(order)
                self.assertEqual(index["claim:abc"]["event_ref"], "era:bbb")

    def test_two_active_resolutions_for_one_claim_refuse_loudly(self):
        # T-B-03. Recency is not a tiebreak for "what did this sentence mean".
        rows = [
            {"claim_id": "claim:abc", "event_mention": "College",
             "event_ref": "era:aaa", "bound_by": "alias", "created_at": NOW},
            {"claim_id": "claim:abc", "event_mention": "the Mission",
             "event_ref": "era:bbb", "bound_by": "alias",
             "created_at": "2026-09-01T00:00:00Z"},
        ]
        with self.assertRaises(eb.EventBindingError) as caught:
            eb.event_resolution_index(rows)
        self.assertEqual(caught.exception.code, "event_resolution_ambiguous")

    def test_resolve_events_is_an_overlay_not_an_edit(self):
        claim = _claim()
        record = eb.validate_event_resolution({
            "claim_id": claim["claim_id"], "event_mention": "College",
            "event_ref": self.era_id, "bound_by": "alias", "created_at": NOW,
        })
        resolved, findings = eb.resolve_events([claim], [record])
        self.assertEqual(findings, [])
        self.assertEqual(resolved[0]["event_ref"], self.era_id)
        self.assertEqual(resolved[0]["event_resolution"]["bound_by"], "alias")
        # The input row is untouched — a receipt on disk is evidence.
        self.assertNotIn("event_ref", claim)

    def test_an_unbound_mention_is_a_named_diagnostic(self):
        claim = _claim(event_mention="Narnia")
        _resolved, findings = eb.resolve_events([claim], [])
        self.assertEqual(findings[0]["finding"], eb.UNBOUND_FINDING)
        self.assertEqual(findings[0]["event_mention"], "Narnia")

    def test_an_alias_added_later_does_not_rewrite_a_filed_binding(self):
        # T-B-04. Aliases reach the future only.
        claim = _claim()
        filed, _ = eb.file_event_resolution(
            self.root, claim_id=claim["claim_id"], event_mention="College",
            event_ref="era:aaa", bound_by="alias", now=NOW,
        )
        # A second era now also answers to "College"…
        for op in ("s5#t1", "s6#t1"):
            ei.file_era_identity(self.root, operation_id=op, occurred_at=NOW)
            ei.file_era_label(self.root, era_id=ei.era_id_for(op),
                              label=f"Era {op}", aliases=["College"], occurred_at=NOW)
        # …and the already-filed decision still says what it said.
        resolved, _ = eb.resolve_events(
            [claim], eb.load_event_resolutions(self.root)
        )
        self.assertEqual(resolved[0]["event_ref"], "era:aaa")
        self.assertEqual(
            eb.load_event_resolutions(self.root)[0]["resolution_id"],
            filed["resolution_id"],
        )


# --------------------------------------------------------------------------
# S5 — `era-record`, the atomic writer
# --------------------------------------------------------------------------

COLLEGE_PAYLOAD = {
    "label": "College Years",
    "aliases": ["College"],
    "era_kind": "stretch",
    "session_ref": "s1",
    "turn_ref": "t1",
    "message_text": "I think of 2007 through 2011 as my College years.",
    "claims": [
        {"claim_type": "date", "subject_mention": "me",
         "event_kind": "period_started", "event_mention": "College",
         "temporal_value": "2007",
         "evidence": "2007 through 2011 as my College years"},
        {"claim_type": "date", "subject_mention": "me",
         "event_kind": "period_ended", "event_mention": "College",
         "temporal_value": "2011",
         "evidence": "2007 through 2011 as my College years"},
    ],
}


class EraRecordTests(unittest.TestCase):
    """§4.4 — one sentence, one act, and replay is a no-op at every step."""

    def setUp(self):
        self.root = _vault(self)

    def test_one_sentence_becomes_one_era_with_two_bound_claims(self):
        # T-NE-01, founder-shaped.
        summary = er.record_era(self.root, COLLEGE_PAYLOAD, now=NOW)
        era_id = summary["era_id"]
        self.assertTrue(summary["steps"]["identity"]["created"])
        self.assertTrue(summary["steps"]["label"]["created"])
        self.assertEqual(summary["steps"]["kind"]["era_kind"], "stretch")

        views = ei.era_views(self.root)
        self.assertEqual(list(views), [era_id])
        self.assertEqual(views[era_id]["label"], "College Years")

        claims = summary["steps"]["claims"]
        self.assertEqual(len(claims["claim_ids"]), 2)
        self.assertEqual({b["event_ref"] for b in claims["bindings"]}, {era_id})
        self.assertEqual({b["bound_by"] for b in claims["bindings"]}, {"target"})

        # And the two dates now group onto the ERA's node, not onto "me".
        index = ts.rebuild_active_index(self.root)
        resolved, _ = eb.resolve_events(
            tt.active_claim_rows(index), eb.load_event_resolutions(self.root)
        )
        self.assertEqual(
            {row["event_ref"] for row in resolved
             if row["claim_type"] != "identity"},
            {era_id},
        )
        result = tt.derive_calculated_timeline(
            index,
            event_resolution_records=eb.load_event_resolutions(self.root),
            era_views=ei.era_views(self.root),
            now=NOW,
        )
        era_node = result.node(era_id)
        self.assertIsNotNone(era_node)
        self.assertEqual(era_node["node_kind"], "period")
        self.assertEqual(era_node["event_kind"], "named_era")
        self.assertEqual(era_node["label"], "College Years")
        self.assertEqual(era_node["best_temporal_value"]["earliest"], "2007")
        self.assertEqual(era_node["best_temporal_value"]["latest"], "2011")

    def test_replaying_the_same_act_writes_nothing(self):
        # T-W-01/02.
        er.record_era(self.root, COLLEGE_PAYLOAD, now=NOW)
        before = _files(self.root)
        again = er.record_era(self.root, COLLEGE_PAYLOAD, now=NOW)
        self.assertFalse(again["steps"]["identity"]["created"])
        self.assertFalse(again["steps"]["label"]["created"])
        self.assertFalse(again["steps"]["kind"]["created"])
        self.assertFalse(any(b["created"] for b in again["steps"]["claims"]["bindings"]))
        self.assertTrue(again["steps"]["publish"]["unchanged"])
        self.assertEqual(before, _files(self.root))

    def test_a_job_that_dies_mid_way_completes_on_the_retry(self):
        # T-W-02/03. Every step is a crash point; the retry under the SAME
        # mutation id converges on the uninterrupted run's exact file set.
        whole = _vault(self)
        er.record_era(whole, COLLEGE_PAYLOAD, now=NOW)
        expected = _files(whole)
        for step in ("identity", "label", "kind", "claims"):
            with self.subTest(died_after=step):
                root = _vault(self)
                er.record_era(root, COLLEGE_PAYLOAD, now=NOW, stop_after=step)
                self.assertLess(len(_files(root)), len(expected))
                er.record_era(root, COLLEGE_PAYLOAD, now=NOW)
                self.assertEqual(_files(root), expected)

    def test_a_rename_through_the_writer_keeps_the_era_id(self):
        # T-NE-17 end to end: the second act names the era it is renaming.
        first = er.record_era(self.root, COLLEGE_PAYLOAD, now=NOW)
        era_id = first["era_id"]
        label_digest = ei._digest_of(
            ei.read_era_record(self.root, first["steps"]["label"]["path"])
        )
        second = er.record_era(self.root, {
            "era_id": era_id,
            "label": "Finding My Direction",
            "aliases": ["College"],
            "supersedes_label": label_digest,
            "session_ref": "s2", "turn_ref": "t7",
        }, now="2026-09-01T00:00:00Z")
        self.assertEqual(second["era_id"], era_id)
        views = ei.era_views(self.root)
        self.assertEqual(list(views), [era_id])
        self.assertEqual(views[era_id]["label"], "Finding My Direction")
        # The claims filed under the old name still point at the same era.
        resolutions = eb.load_event_resolutions(self.root)
        self.assertEqual({r["event_ref"] for r in resolutions}, {era_id})

    def test_a_graduation_keeps_its_own_event_ref(self):
        # T-B-05. "I graduated in 2011 during College" is a date claim about
        # the GRADUATION plus (E2) a membership assertion. The era's own
        # bounds are not moved by it, and the graduation does not become a
        # bound of College just because the sentence said the word.
        er.record_era(self.root, COLLEGE_PAYLOAD, now=NOW)
        era_id = ei.era_id_for("s1#t1")
        er.record_era(self.root, {
            "era_id": era_id,
            "session_ref": "s1", "turn_ref": "t2",
            "message_text": "I graduated in 2011 during College.",
            "claims": [
                {"claim_type": "date", "subject_mention": "me",
                 "event_kind": "graduation", "temporal_value": "2011",
                 "evidence": "I graduated in 2011"},
            ],
        }, now=NOW)
        index = ts.rebuild_active_index(self.root)
        result = tt.derive_calculated_timeline(
            index,
            event_resolution_records=eb.load_event_resolutions(self.root),
            era_views=ei.era_views(self.root),
            now=NOW,
        )
        graduation = [node for node in result.nodes
                      if node["event_kind"] == "graduation"]
        self.assertEqual(len(graduation), 1)
        self.assertNotEqual(graduation[0]["node_id"], era_id)
        era_node = result.node(era_id)
        self.assertEqual(era_node["best_temporal_value"]["earliest"], "2007")
        self.assertEqual(era_node["best_temporal_value"]["latest"], "2011")
        self.assertNotIn(graduation[0]["node_id"], era_node["input_claim_refs"])

    def test_two_eras_sharing_an_alias_bind_to_neither_and_mint_a_question(self):
        er.record_era(self.root, {
            "label": "The Mission", "session_ref": "a", "turn_ref": "1",
        }, now=NOW)
        er.record_era(self.root, {
            "label": "Mission Years", "aliases": ["The Mission"],
            "session_ref": "b", "turn_ref": "1",
        }, now=NOW)
        # A THIRD era is the session's target: §4.3's target rule wins only on
        # the target's OWN exact label, so it must not break a tie it is not
        # in — `test_the_target_does_not_break_a_tie_it_is_not_in` pins the
        # binder half, and this pins the writer half.
        er.record_era(self.root, {
            "label": "College Years", "session_ref": "c", "turn_ref": "0",
        }, now=NOW)
        summary = er.record_era(self.root, {
            "era_id": ei.era_id_for("c#0"),
            "session_ref": "c", "turn_ref": "1",
            "message_text": "That was during the Mission.",
            "claims": [{"claim_type": "date", "subject_mention": "me",
                        "event_kind": "job", "event_mention": "the Mission",
                        "temporal_value": "2003",
                        "evidence": "That was during the Mission"}],
        }, now=NOW)
        binding = summary["steps"]["claims"]["bindings"][0]
        self.assertIsNone(binding["event_ref"])
        self.assertEqual(binding["bound_by"], "none")
        self.assertEqual(binding["work_item"]["kind"], eb.AMBIGUOUS_WORK_ITEM_KIND)
        self.assertEqual(len(binding["work_item"]["candidates"]), 2)

    def test_a_mention_nothing_answers_to_is_a_named_miss(self):
        summary = er.record_era(self.root, {
            "label": "College Years", "session_ref": "s1", "turn_ref": "t1",
            "message_text": "That was during Narnia.",
            "claims": [{"claim_type": "date", "subject_mention": "me",
                        "event_kind": "job", "event_mention": "Narnia",
                        "temporal_value": "2003",
                        "evidence": "That was during Narnia"}],
        }, now=NOW)
        binding = summary["steps"]["claims"]["bindings"][0]
        self.assertIsNone(binding["event_ref"])
        self.assertEqual(binding["finding"], eb.UNBOUND_FINDING)

    def test_within_a_frame_is_a_possibility_and_never_a_bound(self):
        # T-NE-09 (§4.2). The era says nothing about when it began; it says
        # it happened inside a frame.
        birth = tc.validate_temporal_claim({
            "claim_type": "date", "subject_mention": "self",
            "event_kind": "birth", "temporal_value": "1981-07-11",
            "evidence": "I was born on 11 July 1981",
            "source_kind": "conversation",
            "source_ref": {"source_id": "conversation:msg-b",
                           "revision": "sha256:" + "2" * 64},
            "extractor_version": "landmark_recorder@1",
        }, now=NOW)
        ts.write_receipt(self.root, {
            "source_ref": birth["source_ref"],
            "extractor_version": "landmark_recorder@1",
            "claims": [birth],
        }, now=NOW)
        summary = er.record_era(self.root, {
            "label": "College Years", "era_kind": "stretch",
            "session_ref": "s1", "turn_ref": "t1",
            "within": "age:self:20s",
            "message_text": "College was in my 20s.",
        }, now=NOW)
        era_id = summary["era_id"]
        self.assertEqual(summary["steps"]["within"]["anchor"], "age:self:20s")
        result = tt.derive_calculated_timeline(
            ts.rebuild_active_index(self.root),
            event_resolution_records=eb.load_event_resolutions(self.root),
            era_views=ei.era_views(self.root),
            constraints=ts.active_ordering_constraints(self.root),
            now=NOW,
        )
        node = result.node(era_id)
        self.assertIsNotNone(node, "the era must reach the projection")
        self.assertIsNone(node["best_temporal_value"])
        self.assertIsNotNone(node.get("possible_temporal_value"))
        self.assertEqual(node["basis"], "inferred")

    def test_an_unknown_payload_key_is_refused_before_a_byte_lands(self):
        before = _files(self.root)
        with self.assertRaises(er.EraRecordError) as caught:
            er.record_era(self.root, {"label": "X", "session_ref": "s",
                                      "turn_ref": "t", "vibes": "good"})
        self.assertEqual(caught.exception.code, "era_payload_unknown_key")
        self.assertEqual(before, _files(self.root))

    def test_a_refused_claim_refuses_the_whole_act(self):
        before = _files(self.root)
        with self.assertRaises(er.EraRecordError) as caught:
            er.record_era(self.root, {
                "label": "X", "session_ref": "s", "turn_ref": "t",
                "message_text": "Ada, Bo, Cy and Della were born in 1979.",
                "claims": [{"claim_type": "date",
                            "subject_mention": "Ada, Bo, Cy and Della",
                            "event_kind": "birth", "temporal_value": "1979",
                            "evidence": "Ada, Bo, Cy and Della"}],
            })
        self.assertEqual(caught.exception.code, "era_payload_claim_refused")
        self.assertEqual(before, _files(self.root))

    def test_memberships_with_no_writer_refuse_the_whole_act(self):
        # ADR 0021: unwired is a loud failure, never a silent under-delivery.
        before = _files(self.root)
        with self.assertRaises(er.EraRecordError) as caught:
            er.record_era(self.root, {
                "label": "X", "session_ref": "s", "turn_ref": "t",
                "memberships": [{"member_node_id": "event:abc",
                                 "relation": "within"}],
            })
        self.assertEqual(caught.exception.code, "era_membership_unwired")
        self.assertEqual(before, _files(self.root))

    def test_a_wired_membership_writer_is_called_once_per_row(self):
        calls = []

        def writer(vault_root, **kwargs):
            calls.append(kwargs)
            return {"assertion_id": f"a{len(calls)}"}, True

        self.addCleanup(setattr, er, "MEMBERSHIP_WRITER", None)
        er.MEMBERSHIP_WRITER = writer
        summary = er.record_era(self.root, {
            "label": "College Years", "session_ref": "s1", "turn_ref": "t1",
            "memberships": [{"member_node_id": "event:abc", "relation": "within",
                             "source_ref": "src:1"}],
        }, now=NOW)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["member_node_id"], "event:abc")
        self.assertEqual(calls[0]["era_node_id"], summary["era_id"])
        self.assertEqual(len(summary["steps"]["memberships"]), 1)


# --------------------------------------------------------------------------
# S7 — stretch vs thread
# --------------------------------------------------------------------------


class StretchOrThreadTests(unittest.TestCase):
    """§4.5 — decided from the words, ambiguous means ASK."""

    def test_a_stated_interval_is_a_stretch(self):
        for said in ("I think of 2007 through 2011 as my College years",
                     "from 1998 to 2004 we were in Austin",
                     "it started in the spring and ended when we moved"):
            with self.subTest(said=said):
                self.assertEqual(er.era_kind_from_words(said), "stretch")

    def test_recurring_presence_is_a_thread(self):
        for said in ("Ruth has been around over the years",
                     "it came and goes, on and off",
                     "ever since, it has been part of things"):
            with self.subTest(said=said):
                self.assertEqual(er.era_kind_from_words(said), "thread")

    def test_a_within_makes_it_a_stretch(self):
        self.assertEqual(
            er.era_kind_from_words("College was in my 20s", has_within=True),
            "stretch",
        )

    def test_ambiguous_is_none_and_never_a_default(self):
        # A default here would mint a span work item against a thing with no
        # honest end and then ask, forever, when it finished.
        self.assertIsNone(er.era_kind_from_words("it was a thing"))
        self.assertIsNone(er.era_kind_from_words(
            "over the years, from 1998 to 2004, on and off"))

    def test_the_flip_preserves_identity_and_swaps_the_open_work_item(self):
        # T-NE-16.
        root = _vault(self)
        summary = er.record_era(root, COLLEGE_PAYLOAD, now=NOW)
        era_id = summary["era_id"]
        kind_digest = ei._digest_of(
            ei.read_era_record(root, summary["steps"]["kind"]["path"])
        )
        flipped = er.flip_era_kind(root, era_id=era_id, era_kind="thread",
                                   supersedes=kind_digest,
                                   now="2026-09-01T00:00:00Z")
        self.assertEqual(flipped["era_id"], era_id)
        self.assertEqual(flipped["span_work_item"], "retired")
        views = ei.era_views(root)
        self.assertEqual(list(views), [era_id])
        self.assertEqual(views[era_id]["era_kind"], "thread")
        self.assertEqual(views[era_id]["label"], "College Years")
        # The claims and their bindings are exactly where they were.
        self.assertEqual(
            {r["event_ref"] for r in eb.load_event_resolutions(root)}, {era_id}
        )
        # And a Focus candidate exists, pending, creating no Focus.
        state = json.loads(
            (root / "state" / "focus_recommendations.json").read_text()
        )
        row, = state["recommendations"]
        self.assertEqual(row["entity"], "College Years")
        self.assertEqual(row["type"], er.THREAD_FOCUS_TYPE)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["reason"], er.THREAD_FOCUS_REASON)

    def test_flipping_back_re_mints_the_span_work_item(self):
        root = _vault(self)
        summary = er.record_era(root, COLLEGE_PAYLOAD, now=NOW)
        era_id = summary["era_id"]
        er.flip_era_kind(root, era_id=era_id, era_kind="thread", now=NOW)
        back = er.flip_era_kind(root, era_id=era_id, era_kind="stretch",
                                now="2026-09-02T00:00:00Z")
        self.assertEqual(back["span_work_item"], "minted")
        self.assertIsNone(back["focus_candidate"])
        self.assertEqual(len(ei.load_era_kinds(root)), 3)

    def test_the_focus_candidate_is_appended_once(self):
        root = _vault(self)
        summary = er.record_era(root, COLLEGE_PAYLOAD, now=NOW)
        era_id = summary["era_id"]
        er.flip_era_kind(root, era_id=era_id, era_kind="thread", now=NOW)
        again = er.flip_era_kind(root, era_id=era_id, era_kind="thread", now=NOW)
        self.assertFalse(again["focus_candidate"]["created"])
        state = json.loads(
            (root / "state" / "focus_recommendations.json").read_text()
        )
        self.assertEqual(len(state["recommendations"]), 1)


class VaultContractTests(unittest.TestCase):
    """The new durable directories are declared, not invented at write time."""

    def test_the_contract_declares_the_era_and_resolution_directories(self):
        import vault_paths  # noqa: PLC0415

        paths = vault_paths.VAULT_DATA_PATHS
        self.assertEqual(paths["era_sources"]["external_path"], "sources/eras")
        self.assertEqual(
            paths["temporal_resolutions"]["external_path"],
            "state/temporal_claims/resolutions",
        )

    def test_every_new_file_ships_in_framework_files(self):
        manifest = json.loads((ROOT / "system" / "version.json").read_text())
        shipped = set(manifest["framework_files"])
        for name in (
            "system/era_identity.py",
            "system/era_record.py",
            "system/event_binding.py",
            "tests/test_eras_e3.py",
            "interactions/timeline/prompt/recorder.md",
            "sources/eras/.gitkeep",
        ):
            self.assertIn(name, shipped, name)


if __name__ == "__main__":
    unittest.main()
