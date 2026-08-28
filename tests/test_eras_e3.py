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
import event_binding as eb  # noqa: E402
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
        ei.migrate_legacy_periods(root, roster_snapshot=LEGACY_ROSTER,
                                  batch="1", dry_run=False, now=NOW)
        blob = "\n".join(
            (root / relative).read_text(encoding="utf-8")
            for relative in sorted(_files(root))
            if relative.startswith("sources/eras/")
        )
        self.assertNotIn("2001", blob)
        self.assertEqual(ts.receipt_relative_paths(root), [])

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
