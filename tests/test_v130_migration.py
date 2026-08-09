"""v130 — two upstream defects the hosted certification harness found.

1. `asked_at: "None"`. v120 made `last_asked_at` a REQUIRED-but-nullable
   rotation key. `rotation.get("last_asked_at", "")` therefore stopped
   returning the missing-key `""` and started returning `None`, which
   `str(...)[:10]` turned into the literal string `"None"` — a non-empty
   string, so the `or answered_date` fallback never fired and every answer
   filed from a fresh rotation carried `asked_at: None` frontmatter.
   Downstream date validation rejects that.

2. No pre-v120 vault migration. v120's `vault_contract.json` made rotation,
   coverage and question_bank BLOCKING-required at bind time, and nothing
   upgraded vaults written by <= v119. An external user applying v116 -> v128
   in one hop ends up with framework code that refuses to open their own
   vault. `update.run_migrations` now carries a v120 block.

Everything here is synthetic: a throwaway vault per test, never the founder
vault and never the repo's own state.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import update  # noqa: E402
import vault_paths  # noqa: E402


QUESTION_BANK = """# Synthetic Lifehug questions

## A: Origins
- [ ] A1: What is your earliest synthetic memory?
"""

# rotation.json exactly as the v116 TEMPLATE shipped it (git show
# v116:system/rotation.json). Kept literal so a future contract change that
# breaks real v116 vaults fails here rather than in someone's terminal.
V116_TEMPLATE_ROTATION = {
    "version": 1,
    "current_pass": 1,
    "pass_names": ["skeleton", "depth", "connections", "polish"],
    "last_question_id": None,
    "last_asked_at": None,
    "questions_asked": 0,
    "questions_answered": 0,
    "next_question_id": None,
    "focus_frequency": 4,
}

V116_TEMPLATE_COVERAGE = {
    "version": 1,
    "last_updated": None,
    "categories": {"A": {"total": 1, "answered": 0, "status": "red"}},
}

# rotation.json as ask.py's mark_question_sent CREATES it when none exists:
# `read_json(ROTATION_FILE, default={})` tolerates a missing file and
# `write_json` writes back only the keys that writer touched. Every one of the
# contract's nine required keys is absent — this is the shape that raises
# "vault rotation has an unsupported schema version".
V116_WRITER_ROTATION = {
    "last_question_id": "A1",
    "last_asked_at": "2026-01-04T09:15:00",
    "questions_asked": 3,
    "sends_today": 1,
    "sends_today_date": "2026-01-04",
    "delivery_counts": {"A1": 2},
}

# Pre-v21 rotation: `focus_frequency` was spelled with the old Focus term.
LEGACY_FREQUENCY_KEY = "spot" "light_frequency"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_embedded_vault(root: Path, *, rotation=None, coverage=None, version=116) -> Path:
    """A pre-v120 workspace in the layout `update.py` actually operates on:
    the framework clone, with durable data under system/ beside it."""
    system = root / "system"
    system.mkdir(parents=True)
    (system / "question-bank.md").write_text(QUESTION_BANK, encoding="utf-8")
    if rotation is not None:
        _write_json(system / "rotation.json", rotation)
    if coverage is not None:
        _write_json(system / "coverage.json", coverage)
    _write_json(system / "version.json", {"version": version, "framework_files": []})
    # apply_version writes the TARGET version's contract before migrations run.
    shutil.copy(SYSTEM / "vault_contract.json", system / "vault_contract.json")
    return root


def make_external_vault(root: Path, *, rotation=None, coverage=None) -> Path:
    """A data-only vault (the hosted/import layout): no system/ directory, so
    rotation and coverage live under state/."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "question-bank.md").write_text(QUESTION_BANK, encoding="utf-8")
    if rotation is not None:
        _write_json(root / "state" / "rotation.json", rotation)
    if coverage is not None:
        _write_json(root / "state" / "coverage.json", coverage)
    return root


def binds(vault: Path, *, layout: str) -> None:
    """Assert the vault passes the SAME validation resolve_vault_root performs.

    resolve_vault_root is validate_minimum_vault_shape plus an optional
    process bind; binding is process-global and would poison sibling tests, so
    the validation half is called directly.
    """
    framework = vault / "system" if layout == "embedded" else SYSTEM
    vault_paths.validate_minimum_vault_shape(vault, framework_system_dir=framework)


class TmpVaultCase(unittest.TestCase):
    def setUp(self):
        # dir=ROOT.parent, not the system temp dir: macOS /var is a symlink and
        # vault_paths refuses to traverse one.
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v130-")
        self._orig = (update.REPO_DIR, update.VERSION_FILE)
        self.addCleanup(self._restore)

    def _restore(self):
        update.REPO_DIR, update.VERSION_FILE = self._orig

    def _point_update_at(self, vault: Path) -> None:
        update.REPO_DIR = vault
        update.VERSION_FILE = vault / "system" / "version.json"


# ---------------------------------------------------------------------------
# Defect 1 — asked_at: "None"
# ---------------------------------------------------------------------------


class AskedAtFrontmatterTests(TmpVaultCase):
    """End-to-end through the real process_answer.py CLI against a synthetic
    external vault — the exact path that produced the bad frontmatter."""

    def _file_answer(self, rotation, *, answered_date="2026-03-09"):
        vault = make_external_vault(
            self.tmp / f"vault-{len(list(self.tmp.iterdir()))}",
            rotation=rotation,
            coverage=V116_TEMPLATE_COVERAGE,
        )
        result = subprocess.run(
            [sys.executable, str(SYSTEM / "process_answer.py"), "A1",
             "--no-compile-wiki", "--answered-date", answered_date],
            input="A synthetic answer written by the test suite.\n",
            capture_output=True, text=True, cwd=str(vault),
            env={"PATH": "/usr/bin:/bin", "HOME": str(vault),
                 "LIFEHUG_VAULT_ROOT": str(vault)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        answer = vault / "answers" / "A1.md"
        self.assertTrue(answer.exists(), result.stdout + result.stderr)
        return answer.read_text(encoding="utf-8")

    def _frontmatter(self, content):
        _, _, rest = content.partition("---\n")
        block, _, _ = rest.partition("\n---")
        fields = {}
        for line in block.splitlines():
            if ":" not in line or line.startswith(" "):
                continue
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip('"')
        return fields

    def test_null_last_asked_at_never_yields_the_string_none(self):
        # The regression, stated as the bug report stated it.
        rotation = dict(V116_TEMPLATE_ROTATION, last_asked_at=None)
        content = self._file_answer(rotation)
        self.assertNotIn("None", content)
        self.assertEqual(self._frontmatter(content)["asked_at"], "2026-03-09")

    def test_recorded_last_asked_at_is_still_used(self):
        rotation = dict(V116_TEMPLATE_ROTATION, last_asked_at="2026-03-01T08:30:00")
        content = self._file_answer(rotation)
        self.assertEqual(self._frontmatter(content)["asked_at"], "2026-03-01")

    def test_asked_at_is_always_a_plain_iso_date(self):
        # Only values the contract admits (string|null) — anything else fails
        # at bind time, long before frontmatter is written.
        for raw in (None, "", "   ", "2026-03-01T08:30:00"):
            with self.subTest(last_asked_at=raw):
                rotation = dict(V116_TEMPLATE_ROTATION, last_asked_at=raw)
                asked = self._frontmatter(self._file_answer(rotation))["asked_at"]
                date.fromisoformat(asked)  # raises if the field is not a date


# ---------------------------------------------------------------------------
# Defect 2 — the missing v120 vault migration
# ---------------------------------------------------------------------------


class V120MigrationTests(TmpVaultCase):
    def test_v116_template_shape_already_satisfies_the_contract(self):
        # Honest finding: the v116 TEMPLATE happens to carry all nine required
        # rotation keys, so a vault whose state files were never rewritten does
        # bind. The migration must therefore be a strict no-op here — the
        # regressions below cover the shapes that genuinely break.
        vault = make_embedded_vault(
            self.tmp / "pristine",
            rotation=V116_TEMPLATE_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
        )
        binds(vault, layout="embedded")
        before = (vault / "system" / "rotation.json").read_bytes()
        self.assertEqual(update.migrate_vault_to_v120(vault), [])
        self.assertEqual((vault / "system" / "rotation.json").read_bytes(), before)

    def test_writer_created_rotation_is_repaired_and_binds(self):
        # The real breakage: rotation.json created by mark_question_sent from
        # `default={}` — none of the nine contract keys, so bind fails.
        vault = make_embedded_vault(
            self.tmp / "writer",
            rotation=V116_WRITER_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
        )
        with self.assertRaises(ValueError):
            binds(vault, layout="embedded")

        changed = update.migrate_vault_to_v120(vault)
        self.assertIn("system/rotation.json", changed)
        binds(vault, layout="embedded")

        after = json.loads((vault / "system" / "rotation.json").read_text(encoding="utf-8"))
        # Every original key/value survives, byte-for-byte in meaning.
        for key, value in V116_WRITER_ROTATION.items():
            self.assertEqual(after[key], value, key)
        # And the contract keys arrived with the framework's own defaults.
        self.assertEqual(after["version"], 1)
        self.assertEqual(after["current_pass"], 1)
        self.assertEqual(after["pass_names"], ["skeleton", "depth", "connections", "polish"])
        self.assertEqual(after["focus_frequency"], 4)
        self.assertEqual(after["questions_answered"], 0)
        self.assertIsNone(after["next_question_id"])

    def test_every_contract_required_key_is_covered(self):
        # Derived from the contract, not from a hand-listed set: if a future
        # revision adds a required key, this fails until the migration fills it.
        contract = json.loads((SYSTEM / "vault_contract.json").read_text(encoding="utf-8"))
        vault = make_embedded_vault(self.tmp / "derived", rotation={}, coverage={})
        update.migrate_vault_to_v120(vault)
        for name, filename in (("rotation", "rotation.json"), ("coverage", "coverage.json")):
            schema = contract["data_paths"][name]["schema"]
            self.assertEqual(schema["validation_policy"], "blocking")
            data = json.loads((vault / "system" / filename).read_text(encoding="utf-8"))
            for key, expected in schema["required_keys"].items():
                self.assertIn(key, data, f"{name}.{key}")
                self.assertTrue(
                    update._v120_matches_type(data[key], expected),
                    f"{name}.{key} is {data[key]!r}, contract wants {expected}",
                )
        binds(vault, layout="embedded")

    def test_pre_v21_frequency_key_is_adopted_not_defaulted(self):
        # A <= v20 vault spells the key with the old Focus term. Taking its
        # VALUE (and dropping the stale key) keeps the user's setting and stops
        # the v21 terminology migration from later renaming it over the top.
        legacy = {k: v for k, v in V116_TEMPLATE_ROTATION.items() if k != "focus_frequency"}
        legacy[LEGACY_FREQUENCY_KEY] = 9
        vault = make_embedded_vault(
            self.tmp / "prev21", rotation=legacy, coverage=V116_TEMPLATE_COVERAGE,
        )
        with self.assertRaises(ValueError):
            binds(vault, layout="embedded")

        update.migrate_vault_to_v120(vault)
        binds(vault, layout="embedded")
        after = json.loads((vault / "system" / "rotation.json").read_text(encoding="utf-8"))
        self.assertEqual(after["focus_frequency"], 9)
        self.assertNotIn(LEGACY_FREQUENCY_KEY, after)

    def test_unsupported_version_is_replaced_and_the_original_parked(self):
        rotation = dict(V116_TEMPLATE_ROTATION, version=0)
        vault = make_embedded_vault(
            self.tmp / "badversion", rotation=rotation, coverage=V116_TEMPLATE_COVERAGE,
        )
        with self.assertRaises(ValueError):
            binds(vault, layout="embedded")

        update.migrate_vault_to_v120(vault)
        binds(vault, layout="embedded")
        after = json.loads((vault / "system" / "rotation.json").read_text(encoding="utf-8"))
        self.assertEqual(after["version"], 1)
        self.assertEqual(after["legacy_version"], 0)  # nothing is destroyed

    def test_wrong_typed_value_is_parked_never_discarded(self):
        rotation = dict(V116_TEMPLATE_ROTATION, current_pass="two", pass_names="skeleton")
        vault = make_embedded_vault(
            self.tmp / "badtypes", rotation=rotation, coverage=V116_TEMPLATE_COVERAGE,
        )
        update.migrate_vault_to_v120(vault)
        binds(vault, layout="embedded")
        after = json.loads((vault / "system" / "rotation.json").read_text(encoding="utf-8"))
        self.assertEqual(after["current_pass"], 1)
        self.assertEqual(after["legacy_current_pass"], "two")
        self.assertEqual(after["pass_names"], ["skeleton", "depth", "connections", "polish"])
        self.assertEqual(after["legacy_pass_names"], "skeleton")

    def test_missing_coverage_file_is_created(self):
        vault = make_embedded_vault(
            self.tmp / "nocoverage", rotation=V116_TEMPLATE_ROTATION, coverage=None,
        )
        with self.assertRaises(ValueError):
            binds(vault, layout="embedded")
        changed = update.migrate_vault_to_v120(vault)
        self.assertIn("system/coverage.json", changed)
        binds(vault, layout="embedded")
        after = json.loads((vault / "system" / "coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(after, {"version": 1, "last_updated": None, "categories": {}})

    def test_external_layout_uses_state_paths_and_creates_the_directory(self):
        vault = make_external_vault(self.tmp / "external", rotation=None, coverage=None)
        changed = update.migrate_vault_to_v120(vault)
        self.assertEqual(sorted(changed), ["state/coverage.json", "state/rotation.json"])
        self.assertFalse((vault / "system").exists())  # never invents a system/
        binds(vault, layout="external")

    def test_migration_is_idempotent(self):
        vault = make_embedded_vault(
            self.tmp / "twice", rotation=V116_WRITER_ROTATION, coverage={},
        )
        self.assertTrue(update.migrate_vault_to_v120(vault))
        snapshot = {
            p.name: p.read_bytes() for p in (vault / "system").iterdir() if p.is_file()
        }
        self.assertEqual(update.migrate_vault_to_v120(vault), [])
        self.assertEqual(
            {p.name: p.read_bytes() for p in (vault / "system").iterdir() if p.is_file()},
            snapshot,
        )
        binds(vault, layout="embedded")

    def test_no_op_on_an_already_current_vault(self):
        vault = make_embedded_vault(
            self.tmp / "current",
            rotation=V116_TEMPLATE_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
            version=128,
        )
        binds(vault, layout="embedded")
        self.assertEqual(update.migrate_vault_to_v120(vault), [])

    def test_non_object_payload_is_salvaged_not_lost(self):
        vault = make_embedded_vault(
            self.tmp / "garbage",
            rotation=V116_TEMPLATE_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
        )
        (vault / "system" / "rotation.json").write_text("[1, 2, 3]\n", encoding="utf-8")
        update.migrate_vault_to_v120(vault)
        binds(vault, layout="embedded")
        salvage = vault / "system" / "rotation.json.pre-v120"
        self.assertEqual(salvage.read_text(encoding="utf-8"), "[1, 2, 3]\n")

    def test_corrupt_json_is_salvaged_not_destroyed(self):
        # Merge-gate blocker (PR #82): a parse error — the interrupted-write
        # case, the most common real reason a vault won't bind — used to fall
        # through the salvage branch and rebuild over the user's bytes.
        vault = make_embedded_vault(
            self.tmp / "corrupt",
            rotation=V116_TEMPLATE_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
        )
        truncated = '{"version": 1, "current_pass": 1, "pass_names": ["skel'
        (vault / "system" / "rotation.json").write_text(truncated, encoding="utf-8")
        update.migrate_vault_to_v120(vault)
        binds(vault, layout="embedded")
        salvage = vault / "system" / "rotation.json.pre-v120"
        self.assertTrue(salvage.exists())
        self.assertEqual(salvage.read_text(encoding="utf-8"), truncated)
        rebuilt = json.loads((vault / "system" / "rotation.json").read_text(encoding="utf-8"))
        self.assertIsInstance(rebuilt, dict)

    def test_migrate_vault_cli_honors_vault_root_env(self):
        # Merge-gate blocker (PR #82): --migrate-vault resolved to REPO_DIR
        # regardless of LIFEHUG_VAULT_ROOT and reported false success while
        # the target vault stayed broken.
        vault = make_external_vault(self.tmp / "external-env")
        _write_json(vault / "state" / "rotation.json", {})
        args = update.argparse.Namespace(vault_root=None)
        with mock.patch.dict(update.os.environ, {"LIFEHUG_VAULT_ROOT": str(vault)}):
            rc = update.cmd_migrate_vault(args)
        self.assertFalse(rc)
        binds(vault, layout="external")

    def test_migrate_vault_cli_vault_root_arg_beats_env(self):
        vault = make_external_vault(self.tmp / "external-arg")
        _write_json(vault / "state" / "rotation.json", {})
        decoy = self.tmp / "decoy"
        decoy.mkdir()
        args = update.argparse.Namespace(vault_root=str(vault))
        with mock.patch.dict(update.os.environ, {"LIFEHUG_VAULT_ROOT": str(decoy)}):
            rc = update.cmd_migrate_vault(args)
        self.assertFalse(rc)
        binds(vault, layout="external")

    def test_migrate_vault_cli_fails_loudly_not_falsely(self):
        args = update.argparse.Namespace(vault_root=str(self.tmp / "does-not-exist"))
        rc = update.cmd_migrate_vault(args)
        self.assertEqual(rc, 1)


class RunMigrationsWiringTests(TmpVaultCase):
    """update.py applies the TARGET version directly, so the v120 block has to
    fire for a current_version anywhere below 120 — not just 119."""

    def _repaired(self, target, current):
        vault = make_embedded_vault(
            self.tmp / f"wire-{target}-{current}",
            rotation=V116_WRITER_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
            version=current,
        )
        self._point_update_at(vault)
        # The v15/v21 blocks import roadmap/focus_migration, which resolve the
        # vault through lifehug_core — NOT through update.REPO_DIR — so leaving
        # them importable would make this test write into the real repo. A None
        # entry makes the import raise, which run_migrations already tolerates,
        # keeping the assertion scoped to the v120 block.
        with mock.patch.dict(sys.modules, {"roadmap": None, "focus_migration": None}):
            update.run_migrations(target, current)
        rotation = json.loads((vault / "system" / "rotation.json").read_text(encoding="utf-8"))
        return vault, "version" in rotation

    def test_fires_from_any_pre_120_version(self):
        for current in (14, 22, 116, 119):
            with self.subTest(current=current):
                vault, repaired = self._repaired(128, current)
                self.assertTrue(repaired, f"v{current} -> v128 left the vault unbindable")
                binds(vault, layout="embedded")

    def test_does_not_fire_below_the_target_or_when_already_current(self):
        _, repaired = self._repaired(119, 116)
        self.assertFalse(repaired)
        _, repaired = self._repaired(128, 120)
        self.assertFalse(repaired)

    def test_runs_before_the_migrations_that_import_lifehug_core(self):
        # v15/v21 import roadmap/focus_migration, which import lifehug_core,
        # which binds the vault AT IMPORT TIME. Ordering the v120 repair after
        # them would guarantee those imports hit an unbindable vault, so the
        # block order is load-bearing, not cosmetic.
        source = (SYSTEM / "update.py").read_text(encoding="utf-8")
        v120 = source.index("if target_version >= 120")
        self.assertLess(v120, source.index("if target_version >= 15"))
        self.assertLess(v120, source.index("if target_version >= 21"))

    def test_standalone_cli_flag_exists(self):
        vault = make_embedded_vault(
            self.tmp / "cli", rotation=V116_WRITER_ROTATION, coverage=V116_TEMPLATE_COVERAGE,
        )
        self._point_update_at(vault)
        update.cmd_migrate_vault(object())
        binds(vault, layout="embedded")
        source = (SYSTEM / "update.py").read_text(encoding="utf-8")
        self.assertIn("--migrate-vault", source)


if __name__ == "__main__":
    unittest.main()
