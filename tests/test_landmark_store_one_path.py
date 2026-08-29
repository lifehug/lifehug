"""One landmark store per vault — the read path and the write path are one file.

Timeline Fix 01 (lifehug-platform#755), Half A. The defect this file exists to
make unrepeatable, in one sentence:

    `system/vault_contract.json` routed the `landmarks` durable-data key to
    `state/landmarks.json` on an EXTERNAL vault and to `system/landmarks.json`
    on an EMBEDDED one, and `system/landmarks.json` was ALSO a framework file
    — so on every embedded vault the landmark store was a 36-byte seed that
    `update.py --apply` re-shipped empty on every release, while the real
    entries sat unread in `state/landmarks.json`.

The consequence the owner saw: a birthday held at DAY precision since
2026-08-25 read as `open`/`count 0`, the Timeline starred *Birth*, and the
conversation asked "What year were you born?".

Two guards, so the class cannot come back:

1. the `landmarks` key resolves to the SAME path under `state/` in BOTH
   layouts (and that is the path the projection's one writer targets);
2. NO durable-data file, in EITHER layout, may resolve to a path that
   `version.json`'s `framework_files` ships to every install — unless
   `update.is_protected` says the updater will never overwrite it. That is
   the general shape of the bug: vault STATE routed at a framework-owned
   path.

Plus the migration for vaults that already carry the seed, in its three
states, and its idempotency.

Synthetic vaults only; NEVER references ~/Workspace/dave. The embedded fixture
carries the founder's SHAPE — a 36-byte template seed at
`system/landmarks.json` beside a populated `state/landmarks.json` — with every
identity synthetic and every date shifted.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "scripts" / "ci"))
sys.path.insert(0, str(ROOT / "tests"))

import check_framework_files  # noqa: E402
import update  # noqa: E402
import vault_paths  # noqa: E402

from tempdirs import root_parent_tmp  # noqa: E402

VERSION = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
FRAMEWORK_FILES = set(VERSION["framework_files"])

#: The landmark store's ONE relative path, in every layout.
STORE_RELATIVE = Path("state") / "landmarks.json"

#: Durable-data files that legitimately resolve to a shipped framework file.
#: Every one must be in `update.PROTECTED_FILES` — the updater skips those, so
#: shipping them cannot blank a vault's data. The reason is part of the row.
FRAMEWORK_SHIPPED_ALLOWLIST = {
    "readme": "README.md is a framework template AND the vault's own front "
              "page; `update.is_protected` skips it on every apply.",
}

#: Durable-data files whose EMBEDDED path is not their external path. Each is a
#: pre-v120 location kept for compatibility and each is protected from being
#: shipped, which is exactly what `landmarks` was not.
EMBEDDED_PATH_EXCEPTIONS = {
    "question_bank": "system/question-bank.md predates the contract; protected, "
                     "and the updater saves the upstream copy beside it.",
    "rotation": "system/rotation.json is a pre-v120 embedded location; protected.",
    "coverage": "system/coverage.json is a pre-v120 embedded location; protected.",
}

# --- the founder's SHAPE, fully synthetic -----------------------------------
SEED_TEMPLATE_BYTES = b'{\n  "version": 1,\n  "domains": {}\n}\n'

POPULATED_STORE = {
    "version": 1,
    "domains": {
        "birth": [
            {
                "domain": "birth",
                "date": {"value": "1968-07-11", "granularity": "day",
                         "basis": "stated", "confidence": "certain"},
            }
        ],
        "children": [
            {"domain": "children", "who": "Wren",
             "date": {"value": "1997-12-21", "granularity": "day",
                      "basis": "stated", "confidence": "certain"}},
            {"domain": "children", "who": "Marlow",
             "date": {"value": "2000-05-10", "granularity": "day",
                      "basis": "stated", "confidence": "certain"}},
        ],
        "residences": [
            {"domain": "residences", "city": "Cedar Falls"},
        ],
    },
}

EMBEDDED_ENTRIES = {
    "version": 1,
    "domains": {
        "schools": [
            {"domain": "schools", "name": "Rockwood High"},
        ],
        "birth": [
            {
                "domain": "birth",
                "date": {"value": "1968-07-11", "granularity": "day",
                         "basis": "stated", "confidence": "certain"},
            }
        ],
    },
}


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class SyntheticLayouts(unittest.TestCase):
    """An embedded vault and an external one, both real directories on disk.

    `vault_paths.vault_layout` compares the vault root against the framework's
    PARENT, and refuses to traverse a symlink — so the temp trees are made the
    way every other test in this repo makes them (`root_parent_tmp`), never at
    a hardcoded system temp path.
    """

    def setUp(self) -> None:
        vault_paths._reset_process_binding_for_tests()
        self.addCleanup(vault_paths._reset_process_binding_for_tests)
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-one-store-")
        # embedded: the vault IS the framework checkout
        self.embedded_vault = self.tmp / "embedded"
        self.embedded_framework_system = self.embedded_vault / "system"
        self.embedded_framework_system.mkdir(parents=True)
        (self.embedded_vault / "state").mkdir()
        # external: a vault beside a framework that is not its own
        self.framework_system = self.tmp / "framework" / "system"
        self.framework_system.mkdir(parents=True)
        self.external_vault = self.tmp / "external"
        (self.external_vault / "state").mkdir(parents=True)

    def relative(self, name: str, *, embedded: bool) -> Path:
        if embedded:
            return vault_paths.vault_relative_path(
                name,
                vault_root=self.embedded_vault,
                framework_system_dir=self.embedded_framework_system,
            )
        return vault_paths.vault_relative_path(
            name,
            vault_root=self.external_vault,
            framework_system_dir=self.framework_system,
        )


class LandmarkStoreOnePathTests(SyntheticLayouts):
    def test_the_layouts_are_what_this_file_says_they_are(self) -> None:
        self.assertEqual(
            vault_paths.vault_layout(
                self.embedded_vault,
                framework_system_dir=self.embedded_framework_system,
            ),
            "embedded",
        )
        self.assertEqual(
            vault_paths.vault_layout(
                self.external_vault, framework_system_dir=self.framework_system
            ),
            "external",
        )

    def test_embedded_and_external_resolve_to_state(self) -> None:
        embedded = self.relative("landmarks", embedded=True)
        external = self.relative("landmarks", embedded=False)
        self.assertEqual(embedded, STORE_RELATIVE)
        self.assertEqual(external, STORE_RELATIVE)
        self.assertEqual(embedded, external)
        self.assertEqual(embedded.parent.name, "state")

    def test_the_checkout_reads_and_writes_one_store_under_state(self) -> None:
        """This checkout IS an embedded vault — the exact shape that broke."""
        import lifehug_core  # noqa: PLC0415
        import timeline  # noqa: PLC0415

        self.assertEqual(timeline.LANDMARKS_STORE, lifehug_core.LANDMARKS_FILE)
        self.assertEqual(
            Path(timeline.LANDMARKS_STORE).relative_to(lifehug_core.REPO_DIR),
            STORE_RELATIVE,
        )
        # `redraw_landmarks` is the one writer and it writes LANDMARKS_STORE,
        # so reader and writer are the same file by construction; what has to
        # hold is that the substrate it draws FROM is the same vault.
        self.assertEqual(
            Path(str(timeline._projection_vault_root())),
            Path(str(lifehug_core.REPO_DIR)),
        )


class FrameworkOwnedPathGuardTests(SyntheticLayouts):
    """No vault STATE may be routed at a path the framework ships. The class."""

    def _file_entries(self):
        for name, entry in sorted(vault_paths.VAULT_DATA_PATHS.items()):
            if entry.get("kind") == "file":
                yield name, entry

    def test_no_data_file_resolves_to_a_shipped_framework_file(self) -> None:
        offenders = []
        for name, _entry in self._file_entries():
            for embedded in (True, False):
                relative = self.relative(name, embedded=embedded)
                if str(relative) not in FRAMEWORK_FILES:
                    continue
                if name in FRAMEWORK_SHIPPED_ALLOWLIST:
                    self.assertTrue(
                        update.is_protected(str(relative)),
                        f"{name} is allowlisted but the updater would overwrite it",
                    )
                    continue
                offenders.append(
                    f"{name} ({'embedded' if embedded else 'external'}) -> {relative}"
                )
        self.assertEqual(
            offenders,
            [],
            "these durable-data files are shipped by `update.py --apply`, which "
            "overwrites the vault's own data with the framework's template",
        )

    def test_a_state_file_keeps_its_state_path_in_both_layouts(self) -> None:
        offenders = []
        for name, entry in self._file_entries():
            if not str(entry["external_path"]).startswith("state/"):
                continue
            if name in EMBEDDED_PATH_EXCEPTIONS:
                self.assertTrue(
                    update.is_protected(str(entry["embedded_path"])),
                    f"{name} is an embedded-path exception but is not protected",
                )
                continue
            if entry["embedded_path"] != entry["external_path"]:
                offenders.append(f"{name}: {entry['external_path']} -> {entry['embedded_path']}")
        self.assertEqual(offenders, [])


class SeedIsGoneTests(unittest.TestCase):
    def test_update_never_ships_system_landmarks_json(self) -> None:
        self.assertFalse(
            "system/landmarks.json" in FRAMEWORK_FILES,
            "the framework still ships the landmark seed to every install",
        )

    def test_the_seed_file_is_not_in_the_framework(self) -> None:
        self.assertFalse((SYSTEM / "landmarks.json").exists())

    def test_the_framework_file_manifest_still_resolves(self) -> None:
        self.assertEqual(check_framework_files.check_framework_files(), [])


class EmbeddedSeedMigrationTests(unittest.TestCase):
    """`update.migrate_embedded_landmark_store`, in its three states."""

    def setUp(self) -> None:
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-seed-migration-")
        self.vault = self.tmp / "vault"
        (self.vault / "system").mkdir(parents=True)
        (self.vault / "state").mkdir()
        self.seed = self.vault / "system" / "landmarks.json"
        self.store = self.vault / "state" / "landmarks.json"
        self.filed: list[tuple[str, list]] = []

    def save_landmarks(self, domain, records):
        self.filed.append((domain, list(records)))
        return list(records)

    def migrate(self):
        return update.migrate_embedded_landmark_store(
            self.vault, save_landmarks=self.save_landmarks
        )

    def test_the_empty_seed_is_removed_and_the_store_is_untouched(self) -> None:
        """The founder's shape: a 36-byte template beside a real store."""
        self.seed.write_bytes(SEED_TEMPLATE_BYTES)
        self.assertEqual(self.seed.stat().st_size, 36)
        write_json(self.store, POPULATED_STORE)
        before = self.store.read_bytes()

        note = self.migrate()

        self.assertIsNotNone(note)
        self.assertFalse(self.seed.exists())
        self.assertEqual(self.store.read_bytes(), before)
        self.assertEqual(self.filed, [])

    def test_a_seed_with_entries_and_no_store_is_filed_into_the_substrate(self) -> None:
        write_json(self.seed, EMBEDDED_ENTRIES)

        note = self.migrate()

        self.assertIsNotNone(note)
        self.assertFalse(self.seed.exists())
        self.assertEqual(
            {domain for domain, _ in self.filed}, {"birth", "schools"}
        )
        self.assertEqual(sum(len(records) for _, records in self.filed), 2)

    def test_both_populated_merges_by_the_stores_own_rule(self) -> None:
        write_json(self.seed, EMBEDDED_ENTRIES)
        write_json(self.store, POPULATED_STORE)
        before = self.store.read_bytes()

        note = self.migrate()

        self.assertIsNotNone(note)
        self.assertFalse(self.seed.exists())
        # The migration files records; `timeline.save_landmarks` merges them by
        # `landmark_entry_key` and the ONE writer redraws. The migration itself
        # never writes the store — a second writer is the dual truth the v225
        # flip removed, coming back.
        self.assertEqual(self.store.read_bytes(), before)
        self.assertEqual(sum(len(records) for _, records in self.filed), 2)

    def test_running_it_again_does_nothing(self) -> None:
        self.seed.write_bytes(SEED_TEMPLATE_BYTES)
        write_json(self.store, POPULATED_STORE)
        self.migrate()
        self.filed.clear()

        self.assertIsNone(self.migrate())
        self.assertEqual(self.filed, [])

    def test_a_stranger_file_with_no_entries_is_left_alone(self) -> None:
        """Not the framework's seed and not the person's entries: say so, keep it."""
        write_json(self.seed, {"version": 1, "domains": {}, "note": "hand-edited"})

        note = self.migrate()

        self.assertIsNotNone(note)
        self.assertTrue(self.seed.exists())
        self.assertEqual(self.filed, [])

    def test_it_refuses_to_file_one_vaults_entries_into_another(self) -> None:
        """An external install updates the FRAMEWORK checkout while the process
        is bound to the person's vault. Entries found there are not that
        vault's data — leave them, say so, delete nothing."""
        write_json(self.seed, EMBEDDED_ENTRIES)

        note = update.migrate_embedded_landmark_store(self.vault)

        self.assertIn("bound to", str(note))
        self.assertTrue(self.seed.exists())

    def test_no_seed_is_no_work(self) -> None:
        write_json(self.store, POPULATED_STORE)
        self.assertIsNone(self.migrate())


if __name__ == "__main__":
    unittest.main()
