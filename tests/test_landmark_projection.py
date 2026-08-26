"""v224 — the entry-store flip: `landmarks.json` becomes a drawing.

Owner amendment 1 to the audited final timeline build plan (2026-08-26), wave
B item B3. The exit gate is one sentence, and most of this file exists to make
it hard to break:

    convert an existing vault's entries, fold the receipts, redraw the file,
    and a reader cannot tell that anything moved.

THE EQUIVALENCE THIS FILE ENFORCES, stated precisely, because "byte-equivalent"
is a claim that has to be defined before it can be tested:

* **Key-order-insensitive.** `lifehug_core.write_json` serializes with
  `indent=2` and NO `sort_keys`, so the file's bytes depend on dict insertion
  order. A re-derivation reproduces the same MAPPING; reproducing the same
  insertion order would additionally require the projector to replay the exact
  sequence of merges that produced the original, which is a property of the
  vault's history and not of its content. So equivalence is compared on parsed
  JSON, not on bytes.
* **Entry-order-PRESERVING.** Within a domain the entries stay in the order
  they were filed. `residences`, `schools` and `work` are `sequence` domains
  whose order is part of the fact, so this one is not negotiable and is
  asserted directly.
* **Value-exact.** Every date, every alternate, every rung, every flag is
  compared by value, including `null`s inside date records.

The deliberate normalizations — the only differences a vault can legitimately
show across the flip — are enumerated in
:meth:`FlipInvisibilityTest.test_the_only_differences_are_the_named_normalizations`
and in the PR body.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402


def date(
    best: str,
    *,
    granularity: str = "year",
    confidence: str = "certain",
    basis: str = "stated",
    anchors: tuple[str, ...] = (),
    provenance: tuple[dict, ...] = (),
) -> dict:
    """One stored date record, normalized exactly as the writer would store it."""
    record = chrono.DateRecord(
        best=best,
        earliest=best,
        latest=best,
        granularity=granularity,
        confidence=confidence,
        basis=basis,
        anchors=anchors,
        provenance=provenance,
    )
    return record.to_dict()


#: A founder-SHAPED vault with every one of the nine domains populated and
#: every stored shape represented: a singleton with no subject (`birth`), a
#: multi-entry set (`children`, four of them — the aggregate defect's own
#: shape, filed correctly), two sequence domains with spans (`residences`,
#: `schools`, `work`), a none terminal (`military`), a sensitive domain
#: (`losses`), a domain whose ladder dates THREE distinct events from one
#: stored date (`partnerships`), alternates on a plain date AND on a span
#: bound (the v222 carriage), a tri-state `living: false`, and a
#: `chain_complete` flag. Synthetic throughout.
FOUNDER_SHAPED: dict[str, list[dict]] = {
    "birth": [
        {
            "domain": "birth",
            "date": date("1962-03-04", granularity="day"),
            "year": "1962",
            "month": "03",
            "day": "04",
        }
    ],
    "family": [
        {
            "domain": "family",
            "label": "Marguerite",
            "who": "Marguerite",
            "relation": "parent",
            "birth": "1934",
            "living": False,
            "date": date("1934"),
        },
        {
            "domain": "family",
            "label": "Odile",
            "who": "Odile",
            "relation": "sibling",
            "birth": "1965",
            "date": date("1965", confidence="approximate"),
        },
    ],
    "residences": [
        {
            "domain": "residences",
            "label": "Pike Hollow",
            "city": "Pike Hollow",
            "address": "44 Larkspur",
            "span": {"start": date("1962"), "end": date("1971")},
            "household": "parents and two siblings",
        },
        {
            "domain": "residences",
            "label": "Calder Street",
            "city": "Brindle",
            "span": {
                "start": date(
                    "1971",
                    confidence="approximate",
                    basis="age",
                    anchors=("birth",),
                    provenance=({"claim": "about nine", "basis": "age"},),
                ),
                "end": date("1980"),
            },
            # The v222 carriage: a claim the winner OUTRANKED, kept beside it.
            "span_alternates": {"start": [date("1972", basis="order")]},
            "chain_complete": True,
        },
    ],
    "schools": [
        {
            "domain": "schools",
            "label": "Brindle Grammar",
            "name": "Brindle Grammar",
            "place": "Brindle",
            "grades": "1-6",
            "span": {"start": date("1968"), "end": date("1974")},
        }
    ],
    "partnerships": [
        {
            "domain": "partnerships",
            "label": "Rosalind",
            "who": "Rosalind",
            "year": "1987",
            "month": "09",
            # ONE stored date for a ladder that dates three distinct events.
            "date": date("1987-09", granularity="month"),
        }
    ],
    "children": [
        {"domain": "children", "label": "Ines", "who": "Ines", "date": date("1989")},
        {"domain": "children", "label": "Tobias", "who": "Tobias", "date": date("1991")},
        {"domain": "children", "label": "Perrine", "who": "Perrine", "date": date("1994")},
        {
            "domain": "children",
            "label": "Aurele",
            "who": "Aurele",
            "date": date("1997", confidence="approximate"),
            # Two rival claims about one birth year — the shape reconcile exists for.
            "date_alternates": [date("1996", basis="order", confidence="inferred")],
        },
    ],
    "work": [
        {
            "domain": "work",
            "label": "Verrey Foundry",
            "what": "pattern maker",
            "where": "Verrey Foundry",
            "span": {"start": date("1981"), "end": date("1999")},
        }
    ],
    "military": [{"domain": "military", "none": True}],
    "losses": [
        {
            "domain": "losses",
            "label": "Marguerite",
            "who": "Marguerite",
            "year": "2008",
            "date": date("2008"),
        }
    ],
}


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-landmark-flip-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        self.store = self.vault / "state" / "landmarks.json"
        self.store.parent.mkdir(parents=True, exist_ok=True)
        # Rebind the STORE only — exactly what every committed landmark test
        # already does. The substrate must follow it there on its own; if it
        # ever reads the process vault instead, these tests write real files
        # into the checkout and fail loudly rather than silently passing.
        patch = mock.patch.object(timeline, "LANDMARKS_STORE", self.store)
        patch.start()
        self.addCleanup(patch.stop)

    def seed(self, landmarks: dict) -> None:
        self.store.write_text(
            json.dumps({"version": 1, "domains": landmarks}, indent=2) + "\n",
            encoding="utf-8",
        )

    def read_store(self) -> dict:
        return json.loads(self.store.read_text(encoding="utf-8"))


class FlipInvisibilityTest(VaultTestCase):
    """Convert -> fold -> project reproduces the pre-flip file."""

    def setUp(self) -> None:
        super().setUp()
        self.before = copy.deepcopy(FOUNDER_SHAPED)
        self.seed(self.before)

    def flip(self) -> dict:
        summary = timeline.flip_landmarks_if_needed()
        self.assertIsNotNone(summary, "a seeded vault must convert")
        return summary

    def test_every_domain_survives_the_flip_with_its_entries_in_order(self) -> None:
        self.flip()
        after = timeline.load_landmarks()
        self.assertEqual(sorted(after), sorted(self.before))
        for domain, entries in self.before.items():
            self.assertEqual(
                [li.landmark_entry_key(e, lp.domain_row_or_none(domain)) for e in entries],
                [
                    li.landmark_entry_key(e, lp.domain_row_or_none(domain))
                    for e in after[domain]
                ],
                f"{domain} entries changed order or membership across the flip",
            )

    def test_the_projection_is_semantically_equivalent(self) -> None:
        self.flip()
        self.assertEqual(timeline.load_landmarks(), self.before)

    def test_the_file_keeps_its_own_shape_and_version(self) -> None:
        self.flip()
        drawn = self.read_store()
        self.assertEqual(drawn["version"], timeline.LANDMARKS_SCHEMA_VERSION)
        self.assertEqual(set(drawn), {"version", "domains"})

    def test_the_only_differences_are_the_named_normalizations(self) -> None:
        """No un-enumerated difference is tolerated anywhere in the file.

        The enumerated set is EMPTY for this fixture: every entry round-trips
        by value. The test is written as a diff rather than as an equality so
        that a future normalization has to be NAMED here to pass, instead of
        being absorbed by a looser assertion.
        """
        self.flip()
        after = timeline.load_landmarks()
        differences = []
        for domain, entries in self.before.items():
            for index, entry in enumerate(entries):
                drawn = after[domain][index]
                for key in sorted(set(entry) | set(drawn)):
                    if entry.get(key) != drawn.get(key):
                        differences.append(
                            f"{domain}[{index}].{key}: {entry.get(key)!r} -> {drawn.get(key)!r}"
                        )
        self.assertEqual(differences, [], "un-enumerated normalization across the flip")

    def test_the_bytes_differ_by_key_order_and_by_nothing_else(self) -> None:
        """THE named normalization, pinned at the byte level.

        A promoted source stores its record as canonical JSON (sorted keys), so
        a redrawn entry comes back with its keys sorted rather than in the order
        the ladder happened to add them. `lifehug_core.write_json` does not
        sort, so the file's BYTES change once, at the flip, and are stable
        forever after.

        Reproducing the original key order would mean storing each entry's key
        POSITIONS and replaying them — recording the order of a dict as though
        it were a fact the person stated. It is not one: no reader can observe
        it (`load_landmarks` hands every reader a dict), and inventing
        structure to preserve is the opposite of what this substrate is for.

        So the guarantee is stated exactly: **re-serialize both sides with
        sorted keys and the bytes are identical.** Anything else that changes —
        a value, a null, an entry, an order — fails here.
        """
        before_bytes = self.store.read_bytes()
        self.flip()
        after_bytes = self.store.read_bytes()
        self.assertNotEqual(before_bytes, after_bytes, "the flip did redraw the file")
        canonical = lambda raw: json.dumps(json.loads(raw), sort_keys=True, indent=2)
        self.assertEqual(canonical(before_bytes), canonical(after_bytes))

    def test_the_none_terminal_survives_as_a_none(self) -> None:
        self.flip()
        self.assertEqual(
            timeline.load_landmarks()["military"], [{"domain": "military", "none": True}]
        )

    def test_alternates_survive_as_rival_claims_and_are_reconciled_back(self) -> None:
        self.flip()
        after = timeline.load_landmarks()
        aurele = after["children"][3]
        self.assertEqual(aurele["date"]["best"], "1997")
        self.assertEqual([a["best"] for a in aurele["date_alternates"]], ["1996"])
        calder = after["residences"][1]
        self.assertEqual(calder["span"]["start"]["best"], "1971")
        self.assertEqual(
            [a["best"] for a in calder["span_alternates"]["start"]], ["1972"]
        )

    def test_the_warrant_survives_the_flip(self) -> None:
        """v222's whole point: a calculated date must not arrive as a stated one."""
        self.flip()
        start = timeline.load_landmarks()["residences"][1]["span"]["start"]
        self.assertEqual(start["basis"], "age")
        self.assertEqual(start["confidence"], "approximate")
        self.assertEqual(start["anchors"], ["birth"])
        self.assertEqual(start["provenance"], [{"claim": "about nine", "basis": "age"}])

    def test_the_readers_still_read(self) -> None:
        """The ladder and the anchor index are the readers the amendment names."""
        before_rows = li.landmark_rows(self.before)
        before_anchors = li.anchors_from_landmarks(self.before)
        self.flip()
        after = timeline.load_landmarks()
        self.assertEqual(li.landmark_rows(after), before_rows)
        self.assertEqual(li.anchors_from_landmarks(after), before_anchors)
        self.assertEqual(
            chrono.to_edtf(timeline.landmark_birth_date(after)), "1962-03-04"
        )

    def test_no_model_was_called(self) -> None:
        """Every receipt names a deterministic rule and no model."""
        self.flip()
        receipts, unreadable = ts.load_receipts(self.vault)
        self.assertEqual(unreadable, [])
        self.assertTrue(receipts)
        for receipt in receipts:
            self.assertEqual(receipt.extractor_version, lp.LEGACY_EXTRACTOR)
            self.assertNotIn("model", receipt.extractor)
            self.assertTrue(receipt.extractor.get("deterministic"))

    def test_every_entry_became_evidence(self) -> None:
        self.flip()
        sources = lp.load_landmark_sources(self.vault)
        self.assertEqual(
            len(sources), sum(len(v) for v in self.before.values())
        )
        for source in sources:
            self.assertTrue((self.vault / source["relative_path"]).is_file())

    def test_the_undisambiguated_date_is_not_given_a_kind_it_never_had(self) -> None:
        """`partnerships` dates three events; the legacy ladder stored one date."""
        self.flip()
        index = ts.read_active_index(self.vault)
        kinds = {
            row.get("event_kind")
            for row in ts.active_claims(index)
            if row.get("claim_type") == "date" and "Rosalind" in row.get("subject_mention", "")
        }
        self.assertEqual(kinds, {lp.UNDISAMBIGUATED_EVENT_KIND})
        self.assertNotIn("married", kinds)


class ConverterIdempotencyTest(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed(copy.deepcopy(FOUNDER_SHAPED))

    def test_a_second_flip_is_a_no_op(self) -> None:
        timeline.flip_landmarks_if_needed()
        first = self.read_store()
        files = sorted(p.relative_to(self.vault).as_posix() for p in self.vault.rglob("*"))
        self.assertIsNone(
            timeline.flip_landmarks_if_needed(), "the flip must run exactly once"
        )
        self.assertEqual(self.read_store(), first)
        self.assertEqual(
            sorted(p.relative_to(self.vault).as_posix() for p in self.vault.rglob("*")),
            files,
            "the second flip wrote a file",
        )

    def test_importing_twice_mints_no_duplicate_claims(self) -> None:
        """The trap: a receipt id binds to a source revision, and redrawing
        changes the file's bytes. An import keyed on the drawing's revision
        would re-import everything on the second call."""
        timeline.flip_landmarks_if_needed()
        before = ts.fold_active_index(self.vault)["counts"]["claims"]
        lp.import_legacy_landmarks(self.vault, timeline.load_landmarks())
        self.assertEqual(ts.fold_active_index(self.vault)["counts"]["claims"], before)

    def test_the_index_rebuilds_from_the_receipts_alone(self) -> None:
        """Wave B's invariant, over landmark claims: delete the index, rebuild,
        get the same bytes."""
        timeline.flip_landmarks_if_needed()
        first = ts.active_index_bytes(ts.read_active_index(self.vault))
        ts.active_index_path(self.vault).unlink()
        self.assertEqual(ts.active_index_bytes(ts.rebuild_active_index(self.vault)), first)

    def test_the_drawing_redraws_identically(self) -> None:
        timeline.flip_landmarks_if_needed()
        first = self.read_store()
        self.store.unlink()
        timeline.redraw_landmarks()
        self.assertEqual(self.read_store(), first)


class PostFlipWriteTest(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed(copy.deepcopy(FOUNDER_SHAPED))
        timeline.flip_landmarks_if_needed()

    def test_a_new_record_lands_as_a_claim_and_appears_in_the_projection(self) -> None:
        before = ts.fold_active_index(self.vault)["counts"]["claims"]
        saved = timeline.save_landmark(
            "work",
            {"domain": "work", "label": "Halloway Press", "what": "compositor",
             "span": {"start": date("2001")}},
        )
        self.assertEqual(saved["label"], "Halloway Press")
        after = timeline.load_landmarks()["work"]
        self.assertEqual([e["label"] for e in after], ["Verrey Foundry", "Halloway Press"])
        self.assertEqual(after[1]["span"]["start"]["best"], "2001")
        self.assertGreater(ts.fold_active_index(self.vault)["counts"]["claims"], before)

    def test_a_later_rung_merges_onto_the_same_entry(self) -> None:
        """The ladder revisits a subject; two tellings are one entry."""
        timeline.save_landmark(
            "schools", {"domain": "schools", "label": "Brindle Grammar",
                        "place": "Brindle, upper town"}
        )
        entries = timeline.load_landmarks()["schools"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["place"], "Brindle, upper town")
        self.assertEqual(entries[0]["grades"], "1-6", "the earlier rung survived")
        self.assertEqual(entries[0]["span"]["end"]["best"], "1974")

    def test_a_rival_date_becomes_an_alternate_rather_than_overwriting(self) -> None:
        timeline.save_landmark(
            "children",
            {"domain": "children", "label": "Ines", "date": date("1988", basis="order",
                                                                 confidence="inferred")},
        )
        ines = timeline.load_landmarks()["children"][0]
        self.assertEqual(ines["date"]["best"], "1989", "the stated claim still wins")
        self.assertEqual([a["best"] for a in ines["date_alternates"]], ["1988"])

    def test_a_none_retires_its_domain_through_a_durable_correction(self) -> None:
        timeline.save_landmark("partnerships", {"domain": "partnerships", "none": True})
        self.assertEqual(
            timeline.load_landmarks()["partnerships"],
            [{"domain": "partnerships", "none": True}],
        )
        corrections = ts.load_temporal_corrections(self.vault)
        self.assertTrue(corrections, "the retirement must leave a record")
        self.assertTrue(any(c.kind == "supersede" for c in corrections))

    def test_the_retired_entry_keeps_its_evidence(self) -> None:
        """Retiring is not forgetting: the source stays, the claims stay,
        and their status says what happened."""
        before = len(lp.load_landmark_sources(self.vault))
        timeline.save_landmark("partnerships", {"domain": "partnerships", "none": True})
        self.assertGreaterEqual(len(lp.load_landmark_sources(self.vault)), before)
        index = ts.fold_active_index(self.vault)
        superseded = [c for c in index["claims"] if c["status"] == "superseded"]
        self.assertTrue(superseded)
        self.assertTrue(all(c.get("status_marks") for c in superseded))

    def test_save_landmarks_files_one_entry_per_record(self) -> None:
        saved = timeline.save_landmarks(
            "children",
            [
                {"domain": "children", "label": "Solene", "date": date("2001")},
                {"domain": "children", "label": "Matthias", "date": date("2003")},
                {"domain": "children", "label": "skipped one", "skipped": True},
            ],
        )
        self.assertEqual(len(saved), 2)
        labels = [e["label"] for e in timeline.load_landmarks()["children"]]
        self.assertEqual(labels[-2:], ["Solene", "Matthias"])


class CorrectionsRoundTripTest(VaultTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed(copy.deepcopy(FOUNDER_SHAPED))
        timeline.flip_landmarks_if_needed()

    def test_retiring_an_entrys_claims_drops_it_from_the_drawing(self) -> None:
        self.assertIn("Brindle Grammar", [e["label"] for e in timeline.load_landmarks()["schools"]])
        lp.retire_entry(
            self.vault, domain="schools", entry_key="brindle grammar",
            reason="filed against the wrong person",
        )
        timeline.redraw_landmarks()
        self.assertEqual(timeline.load_landmarks().get("schools", []), [])

    def test_retracting_one_date_claim_promotes_its_alternate(self) -> None:
        aurele_before = timeline.load_landmarks()["children"][3]
        self.assertEqual(aurele_before["date"]["best"], "1997")
        index = ts.fold_active_index(self.vault)
        winner = [
            row["claim_id"]
            for row in ts.active_claims(index)
            if row.get("claim_type") == "date"
            and row.get("subject_mention") == "Aurele"
            and (row.get("temporal_value") or {}).get("best") == "1997"
        ]
        self.assertEqual(len(winner), 1)
        ts.retract_claims(self.vault, winner, reason="that was her cousin's year")
        timeline.redraw_landmarks()
        aurele_after = timeline.load_landmarks()["children"][3]
        self.assertEqual(aurele_after["date"]["best"], "1996")
        self.assertNotIn("date_alternates", aurele_after)

    def test_nothing_is_ever_deleted(self) -> None:
        lp.retire_entry(
            self.vault, domain="schools", entry_key="brindle grammar", reason="wrong"
        )
        index = ts.fold_active_index(self.vault)
        self.assertTrue(
            any(c["status"] == "superseded" for c in index["claims"]),
            "the retired claims must still be on disk with their marks",
        )


class MigrationStateMachineTest(VaultTestCase):
    def test_pre_flip_then_one_compile_then_a_second(self) -> None:
        self.seed(copy.deepcopy(FOUNDER_SHAPED))
        self.assertFalse(lp.legacy_import_done(self.vault))

        first = timeline.flip_landmarks_if_needed()
        self.assertIsNotNone(first)
        self.assertTrue(lp.legacy_import_done(self.vault))
        self.assertEqual(timeline.load_landmarks(), FOUNDER_SHAPED)

        self.assertIsNone(timeline.flip_landmarks_if_needed())
        self.assertEqual(timeline.load_landmarks(), FOUNDER_SHAPED)

    def test_an_empty_vault_does_not_flip(self) -> None:
        self.seed({})
        self.assertIsNone(timeline.flip_landmarks_if_needed())
        self.assertFalse(lp.legacy_import_done(self.vault))

    def test_a_vault_with_no_store_at_all_does_not_flip(self) -> None:
        self.assertIsNone(timeline.flip_landmarks_if_needed())

    def test_an_unflipped_vault_flips_before_its_first_write(self) -> None:
        """A record can never land in a half-flipped vault."""
        self.seed(copy.deepcopy(FOUNDER_SHAPED))
        timeline.save_landmark("work", {"domain": "work", "label": "Halloway Press"})
        self.assertTrue(lp.legacy_import_done(self.vault))
        labels = [e["label"] for e in timeline.load_landmarks()["work"]]
        self.assertEqual(labels, ["Verrey Foundry", "Halloway Press"])

    def test_a_hand_seeded_entry_without_a_domain_key_still_converts(self) -> None:
        """Two committed tests seed the store by hand in exactly this shape."""
        self.seed({"birth": [{"label": "birth", "date": date("1962-03-04",
                                                             granularity="day")}]})
        timeline.flip_landmarks_if_needed()
        entries = timeline.load_landmarks()["birth"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["date"]["best"], "1962-03-04")


class WriterGuardTest(unittest.TestCase):
    """The build-failing guard: exactly ONE production writer of the store.

    Recurring-defect doctrine. `timeline.save_landmark` was the file's only
    writer before the flip and `timeline.redraw_landmarks` is its only writer
    after it; the danger is a future caller re-adding a direct write and
    quietly restoring the dual truth the flip removed. So this walks the AST of
    every module in `system/` rather than grepping, and it keys on ALL the
    names the store is reachable under — `LANDMARKS_STORE` is an alias of
    `lifehug_core.LANDMARKS_FILE`, which is itself `_data("landmarks")`.
    """

    WRITE_CALLS = {"write_json", "write_text", "write_bytes", "dump",
                   "atomic_write_vault_text", "atomic_write_vault_bytes"}
    STORE_NAMES = {"LANDMARKS_STORE", "LANDMARKS_FILE"}
    ALLOWED = {("timeline.py", "redraw_landmarks")}

    def _writes(self) -> list[tuple[str, str, int]]:
        found: list[tuple[str, str, int]] = []
        for path in sorted((ROOT / "system").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(function):
                    if not isinstance(node, ast.Call):
                        continue
                    name = (
                        node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", "")
                    )
                    if name not in self.WRITE_CALLS:
                        continue
                    targets = [
                        arg.id for arg in node.args if isinstance(arg, ast.Name)
                    ] + [
                        arg.attr for arg in node.args if isinstance(arg, ast.Attribute)
                    ]
                    if self.STORE_NAMES & set(targets):
                        found.append((path.name, function.name, node.lineno))
        return found

    def test_only_one_writer_of_the_landmark_store(self) -> None:
        writers = {(module, function) for module, function, _ in self._writes()}
        self.assertEqual(
            writers,
            self.ALLOWED,
            "state/landmarks.json is a projection: only "
            "timeline.redraw_landmarks may write it",
        )

    def test_no_module_writes_the_store_path_by_literal(self) -> None:
        offenders = []
        for path in sorted((ROOT / "system").glob("*.py")):
            if path.name == "landmark_projection.py":
                continue  # names the path in prose only; asserted below
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "state/landmarks.json":
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_the_projector_derives_content_and_never_a_path(self) -> None:
        """`landmark_projection` must not learn where the store lives — the
        embedded/external layout split is resolved once, in `lifehug_core`."""
        source = (ROOT / "system" / "landmark_projection.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "state/landmarks.json":
                self.fail(
                    "landmark_projection resolved the store path itself; "
                    "that is timeline.LANDMARKS_STORE's job"
                )


class VaultRootDerivationTest(unittest.TestCase):
    """The drawing and its evidence must never land in different vaults."""

    def root_for(self, store: str) -> str:
        with mock.patch.object(timeline, "LANDMARKS_STORE", Path(store)):
            return str(timeline._projection_vault_root())

    def test_an_external_layout_store_resolves_to_its_vault(self) -> None:
        self.assertEqual(self.root_for("/vaults/mine/state/landmarks.json"), "/vaults/mine")

    def test_an_embedded_layout_store_resolves_to_its_vault(self) -> None:
        self.assertEqual(self.root_for("/checkout/system/landmarks.json"), "/checkout")

    def test_a_rebound_store_takes_the_substrate_with_it(self) -> None:
        """The committed landmark tests rebind LANDMARKS_STORE to a bare tmp
        file. The substrate must follow, or a test run writes into the repo."""
        self.assertEqual(self.root_for("/tmp/scratch-123/landmarks.json"), "/tmp/scratch-123")

    def test_the_root_is_never_the_process_binding(self) -> None:
        import lifehug_core  # noqa: PLC0415

        derived = self.root_for("/tmp/somewhere-else/landmarks.json")
        self.assertNotEqual(derived, str(lifehug_core.REPO_DIR))


class ConverterUnitTest(unittest.TestCase):
    """The pure half, with no vault at all."""

    SOURCE = {"source_id": "landmark:entry-test", "revision": "sha256:" + "ab" * 32}

    def claims(self, domain: str, entry: dict) -> list[dict]:
        return lp.entry_claims(domain, entry, source_ref=self.SOURCE,
                               now="2026-08-26T00:00:00Z")

    def test_every_entry_gets_exactly_one_identity_claim(self) -> None:
        for domain, entries in FOUNDER_SHAPED.items():
            for entry in entries:
                identities = [
                    c for c in self.claims(domain, entry) if c["claim_type"] == "identity"
                ]
                self.assertEqual(len(identities), 1, f"{domain}: {entry.get('label')}")

    def test_a_none_entry_produces_an_identity_claim_and_no_dates(self) -> None:
        claims = self.claims("military", {"domain": "military", "none": True})
        self.assertEqual([c["claim_type"] for c in claims], ["identity"])
        self.assertEqual(claims[0]["subject_mention"], "military")

    def test_a_span_becomes_two_claims_with_their_own_warrants(self) -> None:
        claims = self.claims("work", FOUNDER_SHAPED["work"][0])
        kinds = {c["event_kind"] for c in claims if c["claim_type"] == "date"}
        self.assertEqual(kinds, {lp.SPAN_START_EVENT_KIND, lp.SPAN_END_EVENT_KIND})

    def test_a_calculated_date_arrives_calculated(self) -> None:
        claims = self.claims("residences", FOUNDER_SHAPED["residences"][1])
        start = [
            c for c in claims
            if c.get("event_kind") == lp.SPAN_START_EVENT_KIND
            and c["temporal_value"]["best"] == "1971"
        ]
        self.assertEqual(len(start), 1)
        self.assertEqual(start[0]["basis"], "calculated")

    def test_the_basis_is_never_upgraded_to_explicit(self) -> None:
        claims = self.claims("children", FOUNDER_SHAPED["children"][3])
        by_year = {c["temporal_value"]["best"]: c["basis"] for c in claims
                   if c["claim_type"] == "date"}
        self.assertEqual(by_year["1997"], "explicit")
        self.assertEqual(by_year["1996"], "inferred")

    def test_every_claim_carries_evidence(self) -> None:
        for domain, entries in FOUNDER_SHAPED.items():
            for entry in entries:
                for claim in self.claims(domain, entry):
                    self.assertTrue(claim["evidence"], f"{domain} claim without evidence")

    def test_claim_ids_are_stable_across_runs(self) -> None:
        entry = FOUNDER_SHAPED["children"][0]
        first = [c["claim_id"] for c in self.claims("children", entry)]
        second = [c["claim_id"] for c in self.claims("children", entry)]
        self.assertEqual(first, second)

    def test_the_skeleton_never_carries_a_date(self) -> None:
        for entries in FOUNDER_SHAPED.values():
            for entry in entries:
                skeleton = lp.skeleton_of(entry)
                for key in lp.TEMPORAL_ENTRY_KEYS:
                    self.assertNotIn(key, skeleton)

    def test_a_domain_the_question_set_never_declared_still_converts(self) -> None:
        claims = self.claims("invented", {"domain": "invented", "label": "x",
                                          "date": date("1990")})
        self.assertEqual(len(claims), 2)
        self.assertEqual(
            [c["event_kind"] for c in claims if c["claim_type"] == "date"],
            [lp.UNDISAMBIGUATED_EVENT_KIND],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
