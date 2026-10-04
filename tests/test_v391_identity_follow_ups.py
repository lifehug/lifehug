"""v391 (lifehug#459, lifehug-platform#987) — identity follow-ups.

1. `lifehug.py entity-roster --convert-identity` is the module's own converter.
2. `identity_work_items`: an ambiguous `person_identity` record is one
   `identity_uncertain` row ("Which James?"), an unknown one is one
   `new_person` row ("New person?"); a resolved one mints nothing (D3).
3. The non-person handle statements already emit `--fold-into` / `--located-in`.

Every fixture is SYNTHETIC.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import general_listener as gl  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import temporal_projection as tp  # noqa: E402
from test_v386_one_record import legacy_founder_shaped  # noqa: E402
from test_v389_compile_by_record import Vault  # noqa: E402
from test_v390_handles import rosters as handle_rosters  # noqa: E402


def person(name, slug, **extra):
    row = {"name": name, "slug": slug, "aliases": [], "qualifies": True}
    row.update(extra)
    return row


ROSTER = {
    "version": 1,
    "type": "person",
    "entities": [
        person("James Orr", "james-orr", relationship="sibling"),
        person("James Pell", "james-pell", relationship="child"),
        person("Mara Quill", "mara-quill", relationship="spouse"),
    ],
}


def ambiguous(name="James"):
    return {
        "name": name,
        "alias_of": None,
        "alias_of_name": None,
        "relationship": None,
        "basis": "statement",
        "evidence": "my brother James came by",
        "resolution": "ambiguous",
        "candidates": ["person/james-pell", "person/james-orr"],
        "file_relationship": None,
    }


def unknown(name="Tobias Rue", resolution="unknown_person", **extra):
    return {
        "name": name,
        "alias_of": None,
        "alias_of_name": None,
        "relationship": "friend",
        "basis": "statement",
        "evidence": "Tobias Rue was my neighbor",
        "resolution": resolution,
        "candidates": [],
        "file_relationship": None,
        **extra,
    }


def resolved():
    return {
        "name": "Mara Ann",
        "alias_of": "person/mara-quill",
        "alias_of_name": "Mara Quill",
        "relationship": "spouse",
        "basis": "statement",
        "evidence": "Mara Ann is my wife",
        "resolution": "resolved",
        "candidates": ["person/mara-quill"],
        "file_relationship": None,
    }


class ConvertIdentityCliDoor(unittest.TestCase):
    def test_cli_and_module_produce_byte_identical_rosters_and_reports(self):
        entities = legacy_founder_shaped()["entities"]
        module = Vault(self, {"person": entities}, {})
        cli = Vault(self, {"person": entities}, {})
        code = (
            "import sys; sys.path.insert(0, %r); import entity_roster as er, json; "
            "print(json.dumps(er.convert_identity(), indent=2, ensure_ascii=False, "
            "sort_keys=True))" % str(SYSTEM)
        )
        module_out = module.run_py("-c", code)
        cli_out = cli.run_py(
            str(SYSTEM / "lifehug.py"), "entity-roster", "--convert-identity"
        )
        self.assertEqual(json.loads(module_out), json.loads(cli_out))
        path = Path("state/entity_rosters/person.json")
        self.assertEqual(
            (module.root / path).read_bytes(), (cli.root / path).read_bytes()
        )
        self.assertNotEqual(
            (cli.root / path).read_text(),
            json.dumps({"version": 1, "type": "person", "entities": entities}),
        )
        # Idempotent: a second CLI run writes nothing.
        before = (cli.root / path).read_bytes()
        again = json.loads(
            cli.run_py(
                str(SYSTEM / "lifehug.py"), "entity-roster", "--convert-identity"
            )
        )
        self.assertFalse(again["person"]["changed"])
        self.assertEqual(before, (cli.root / path).read_bytes())

    def test_dry_run_through_the_door_writes_nothing(self):
        vault = Vault(self, {"person": legacy_founder_shaped()["entities"]}, {})
        path = vault.root / "state/entity_rosters/person.json"
        before = path.read_bytes()
        report = json.loads(
            vault.run_py(
                str(SYSTEM / "lifehug.py"),
                "entity-roster",
                "--convert-identity",
                "--dry-run",
            )
        )
        self.assertTrue(report["person"]["changed"])
        self.assertEqual(before, path.read_bytes())


class IdentityWorkItems(unittest.TestCase):
    def test_ambiguous_is_one_identity_uncertain_row_naming_both(self):
        rows = gl.identity_work_items([ambiguous()], ROSTER)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "identity_uncertain")
        self.assertEqual(row["prompt_intent"], "Which James?")
        self.assertEqual(
            {c["ref"]: c["name"] for c in row["candidates"]},
            {"person/james-orr": "James Orr", "person/james-pell": "James Pell"},
        )
        self.assertEqual(row["evidence"], "my brother James came by")
        self.assertTrue(row["work_item_id"].startswith("work:"))
        self.assertNotIn("owner_choice_argv", row)

    def test_the_id_is_the_one_mirror_derives(self):
        row = gl.identity_work_items([ambiguous()], ROSTER)[0]
        import identity_resolution as ir  # noqa: PLC0415

        self.assertEqual(
            row["work_item_id"],
            twi.canonical_work_item_id(
                kind="identity_uncertain",
                subject_ref=ir.unresolved_subject_ref("James"),
                requested_field="identity",
            ),
        )

    def test_new_person_is_a_registered_kind(self):
        self.assertIn("new_person", tp.WORK_ITEM_KINDS)

    def test_unknown_person_and_unknown_handle_are_new_person_rows(self):
        rows = gl.identity_work_items(
            [unknown(), unknown("Pia Voss", "unknown_handle", handle="@pia")], ROSTER
        )
        self.assertEqual([r["kind"] for r in rows], ["new_person", "new_person"])
        first = rows[0]
        self.assertEqual(first["prompt_intent"], "New person?")
        self.assertEqual(first["evidence"], "Tobias Rue was my neighbor")
        self.assertEqual(
            first["owner_choice_argv"],
            [
                "entity-verdict",
                "person",
                "tobias-rue",
                "clear",
                "--ensure",
                "--name",
                "Tobias Rue",
            ],
        )
        self.assertEqual(rows[1]["handle"], "@pia")
        self.assertNotEqual(first["work_item_id"], rows[1]["work_item_id"])

    def test_resolved_mints_nothing_and_never_an_ensure_invocation(self):
        self.assertEqual(gl.identity_work_items([resolved()], ROSTER), [])
        for argv in gl.identity_invocations([resolved(), ambiguous(), unknown()]):
            self.assertNotIn("--ensure", argv)

    def test_idempotent_and_deduplicated(self):
        records = [ambiguous(), unknown(), resolved(), ambiguous(), unknown()]
        once = gl.identity_work_items(records, ROSTER)
        self.assertEqual(len(once), 2)
        self.assertEqual(once, gl.identity_work_items(records, ROSTER))
        self.assertEqual(
            once, gl.identity_work_items(list(reversed(records)), ROSTER)[::-1]
        )

    def test_the_candidate_set_moves_the_digest_not_the_identity(self):
        two = gl.identity_work_items([ambiguous()], ROSTER)[0]
        record = ambiguous()
        record["candidates"].append("person/mara-quill")
        three = gl.identity_work_items([record], ROSTER)[0]
        self.assertEqual(two["work_item_id"], three["work_item_id"])
        self.assertNotEqual(two["candidates_digest"], three["candidates_digest"])

    def test_cli_subcommand_reads_listener_json_and_writes_nothing(self):
        vault = Vault(self, {"person": ROSTER["entities"]}, {})
        before = (vault.root / "state/entity_rosters/person.json").read_bytes()
        payload = json.dumps(
            {
                "person_identity": [ambiguous(), unknown(), resolved()],
                "person_roster": ROSTER,
            }
        )
        done = subprocess.run(
            [sys.executable, str(SYSTEM / "lifehug.py"), "identity-work-items"],
            input=payload,
            env=vault.env,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=vault.root,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        items = json.loads(done.stdout)["work_items"]
        self.assertEqual(
            items, gl.identity_work_items([ambiguous(), unknown(), resolved()], ROSTER)
        )
        self.assertEqual(
            before, (vault.root / "state/entity_rosters/person.json").read_bytes()
        )

    def test_listen_to_answer_outcome_carries_the_rows(self):
        reply = json.dumps(
            {
                "landmarks": [],
                "people": [],
                "claims": [],
                "identity_assertions": [],
                "person_identity": [
                    {
                        "name": "Tobias Rue",
                        "refers_to": "",
                        "relationship": "unknown",
                        "evidence": "Tobias Rue was my aunt",
                    }
                ],
            }
        )
        outcome = lr.listen_to_answer(
            answer="Tobias Rue was my aunt.",
            call=lambda prompt, model: reply,
            person_roster=ROSTER,
        )
        self.assertEqual(
            [r["kind"] for r in outcome.identity_work_items], ["new_person"]
        )


class NonPersonHandleStatementsFileThroughTheVerdictVerb(unittest.TestCase):
    def test_same_as_a_handle_folds_an_object_and_in_a_handle_contains_a_place(self):
        rosters = handle_rosters()
        fold = gl.handle_statement_records(
            "One pair of clothes is the same as @orange-shorts.",
            rosters,
            subject="One pair of clothes",
            subject_ref="object/one-pair-of-clothes",
        )
        self.assertEqual(
            gl.handle_statement_invocations(fold),
            [
                [
                    "entity-verdict",
                    "object",
                    "one-pair-of-clothes",
                    "clear",
                    "--fold-into",
                    "orange-shorts",
                ]
            ],
        )
        place = gl.handle_statement_records("@orchard-cove is in @california.", rosters)
        self.assertEqual(
            gl.handle_statement_invocations(place),
            [
                [
                    "entity-verdict",
                    "place",
                    "orchard-cove",
                    "clear",
                    "--located-in",
                    "california",
                ]
            ],
        )


if __name__ == "__main__":
    unittest.main()
