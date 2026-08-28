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
