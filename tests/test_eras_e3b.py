"""O-E3b — the memberships leg is alive: `era-record` binds O-E2's real writer.

Contract: `docs/pr-specs/eras-o-e3-era-record.md` §4.4 step 5 and T-B-05;
`docs/pr-specs/eras-o-e2-memberships.md` for the receipt shape. Controlling
design: lifehug-platform `docs/design/eras.md` §2.3, §2.4, §4.4.

`era_record` resolved the O-E2 seam by lazily importing `era_membership`
(singular) and reaching for a `file_membership_assertion` inside it. v247
shipped `era_memberships` with `file_era_membership`. The import raised, the
seam answered `None`, and — exactly as ADR 0021 asks — `era-record` refused
the WHOLE act for every payload carrying `memberships`. So the atomic
writer's fifth leg was never performed on any vault (lifehug#270).

Every negative test here was run against the unmodified base revision
(90bdc57) first and SEEN failing; the evidence is in the PR body.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import era_identity as ei  # noqa: E402
import era_memberships as em  # noqa: E402
import era_record as er  # noqa: E402
import event_binding as eb  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-27T12:00:00Z"

#: T-B-05's sentence. The graduation is its own event with its own date; the
#: membership is a SEPARATE assertion that the graduation sits inside College.
#: The era's own bounds are not moved by either.
GRADUATION_PAYLOAD = {
    "label": "College Years",
    "aliases": ["College"],
    "era_kind": "stretch",
    "session_ref": "s1",
    "turn_ref": "t1",
    "message_text": "I graduated in 2011 during College.",
    "claims": [
        {"claim_type": "date", "subject_mention": "me",
         "event_kind": "graduation", "event_mention": "College",
         "temporal_value": "2011",
         "evidence": "I graduated in 2011"},
    ],
    "memberships": [
        {"member_node_id": "event:graduation-2011", "relation": "within"},
    ],
}


def _executable_string_literals(path: Path) -> list[str]:
    """Every string constant in one file that is NOT a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            first = body[0] if body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _vault(case: unittest.TestCase) -> Path:
    root = root_parent_tmp(case, ROOT, prefix="eras-e3b-")
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    return root


def _receipts(root: Path) -> list[Path]:
    base = root / em.MEMBERSHIP_SOURCES_DIR
    return sorted(base.glob("*.md")) if base.is_dir() else []


def _files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


# --------------------------------------------------------------------------
# The seam itself
# --------------------------------------------------------------------------


class MembershipSeamTests(unittest.TestCase):
    """ADR 0021 — ONE writer, bound per host, never a second implementation."""

    def test_the_seam_resolves_to_o_e2s_real_writer(self):
        # The whole defect, in one assertion: with nothing overriding it, the
        # seam has to answer a callable. On the base revision it answered None
        # because `era_membership` (singular) is not a module.
        self.assertIsNone(er.MEMBERSHIP_WRITER)
        self.assertIsNotNone(er.membership_writer())

    def test_the_seam_names_a_module_and_function_that_exist(self):
        self.assertTrue((ROOT / "system" / f"{er.MEMBERSHIP_MODULE}.py").is_file())
        module = __import__(er.MEMBERSHIP_MODULE)
        self.assertTrue(callable(getattr(module, er.MEMBERSHIP_FUNCTION, None)))
        # And it is O-E2's, not a copy living here.
        self.assertIs(module, em)
        self.assertIs(getattr(module, er.MEMBERSHIP_FUNCTION), em.file_era_membership)

    def test_era_record_files_no_receipt_of_its_own(self):
        # ADR 0021's actual content: `era_record` must not grow a parallel
        # writer. It may name O-E2's MODULE and FUNCTION — that is the binding
        # — but never O-E2's storage layout: the receipt directory is reached
        # only by calling `membership_relative_path`. A literal path here would
        # be the first line of the second implementation. (Docstrings are
        # excluded: prose that cites the contract is the point, not a leak.)
        literals = _executable_string_literals(ROOT / "system" / "era_record.py")
        leaked = sorted(
            text for text in literals if em.MEMBERSHIP_SOURCES_DIR in text
        )
        self.assertEqual(leaked, [])
        self.assertIn(er.MEMBERSHIP_MODULE, literals)

    def test_the_default_basis_is_one_the_receipt_writer_accepts(self):
        # `"stated"` — the base revision's default — is not a claim basis, so
        # every default row would have been refused the moment the seam was
        # wired. Latent behind a dead import is still wrong.
        from temporal_claims import CLAIM_BASES

        self.assertIn(er.MEMBERSHIP_DEFAULT_BASIS, CLAIM_BASES)
        self.assertIn(er.MEMBERSHIP_DEFAULT_RELATION, em.ASSERTION_RELATIONS)

    def test_an_unwired_seam_still_refuses_the_whole_act(self):
        # The guard that made the defect harmless rather than corrupting must
        # survive the fix.
        root = _vault(self)
        self.addCleanup(setattr, er, "membership_writer", er.membership_writer)
        er.membership_writer = lambda: None
        before = _files(root)
        with self.assertRaises(er.EraRecordError) as caught:
            er.record_era(root, {
                "label": "College Years", "session_ref": "s1", "turn_ref": "t1",
                "memberships": [{"member_node_id": "event:abc"}],
            }, now=NOW)
        self.assertEqual(caught.exception.code, "era_membership_unwired")
        self.assertEqual(before, _files(root))


# --------------------------------------------------------------------------
# T-B-05 end to end
# --------------------------------------------------------------------------


class GraduationDuringCollegeTests(unittest.TestCase):
    """T-B-05 — one date claim with its own `event_ref`, ONE membership."""

    def setUp(self):
        self.root = _vault(self)

    def test_one_sentence_files_the_claim_and_one_membership(self):
        summary = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)
        era_id = summary["era_id"]

        # The date claim exists and its resolution binds the GRADUATION to the
        # era by its own `event_ref` — the era's bounds are untouched.
        claims = summary["steps"]["claims"]
        self.assertEqual(len(claims["claim_ids"]), 1)
        binding = claims["bindings"][0]
        self.assertEqual(binding["event_ref"], era_id)
        resolutions = eb.load_event_resolutions(self.root)
        self.assertEqual([r["claim_id"] for r in resolutions], claims["claim_ids"])

        # The fifth leg actually moved the vault: ONE receipt on disk.
        receipts = _receipts(self.root)
        self.assertEqual(len(receipts), 1)
        rows = em.active_era_memberships(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["member_node_id"], "event:graduation-2011")
        self.assertEqual(rows[0]["era_node_id"], era_id)
        self.assertEqual(rows[0]["relation"], "within")
        self.assertEqual(rows[0]["basis"], er.MEMBERSHIP_DEFAULT_BASIS)

        # And the summary says so, honestly, per row.
        step = summary["steps"]["memberships"]
        self.assertEqual(len(step), 1)
        self.assertTrue(step[0]["created"])
        self.assertEqual(step[0]["assertion_id"], rows[0]["assertion_id"])
        self.assertEqual(step[0]["path"], rows[0]["relative_path"])

    def test_the_receipt_cites_this_acts_own_promoted_source_at_a_revision(self):
        summary = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)
        promoted = summary["steps"]["claims"]["source_ref"]
        row = em.active_era_memberships(self.root)[0]
        # `source_id@revision` — the WHOLE ref. A bare `source_id` (the base
        # revision's spelling) would key the assertion's identity on half of
        # the evidence.
        self.assertEqual(
            row["evidence_source_ref"],
            f"{promoted['source_id']}@{promoted['revision']}",
        )
        self.assertIn("@", row["evidence_source_ref"])
        self.assertEqual(row["evidence_source_ref"], em._source_key(promoted))  # noqa: SLF001

    def test_a_row_that_names_its_own_source_is_not_overruled(self):
        payload = dict(GRADUATION_PAYLOAD)
        payload["memberships"] = [{
            "member_node_id": "event:graduation-2011",
            "relation": "within",
            "source_ref": {"source_id": "landmark:entry-abc", "revision": "a" * 40},
        }]
        er.record_era(self.root, payload, now=NOW)
        row = em.active_era_memberships(self.root)[0]
        self.assertEqual(row["evidence_source_ref"], f"landmark:entry-abc@{'a' * 40}")

    def test_a_membership_with_no_claims_cites_the_operation(self):
        # No message, no promotion — the act itself is the citation, because
        # O-E2 refuses an empty `source_ref` outright.
        summary = er.record_era(self.root, {
            "label": "College Years", "session_ref": "s1", "turn_ref": "t1",
            "memberships": [{"member_node_id": "event:abc"}],
        }, now=NOW)
        self.assertNotIn("claims", summary["steps"])
        row = em.active_era_memberships(self.root)[0]
        self.assertEqual(row["evidence_source_ref"], ei.turn_operation_id("s1", "t1"))

    def test_publish_sees_the_memberships_in_the_fold(self):
        # Step 6 runs before step 7 for a reason: the projection this act
        # produces has to contain what this act just wrote.
        summary = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)
        self.assertIn("publish", summary["steps"])
        self.assertEqual(len(em.active_era_memberships(self.root)), 1)
        self.assertFalse(summary["steps"]["publish"]["unchanged"])

    def test_describe_reports_the_leg(self):
        summary = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)
        lines = er.describe(summary)
        self.assertTrue(any("memberships: 1 assertion(s)" in line for line in lines))


# --------------------------------------------------------------------------
# Replay and mid-way retry (T-W-02/03)
# --------------------------------------------------------------------------


class MembershipReplayTests(unittest.TestCase):
    """The fifth leg is a no-op on replay, by identity — not by a lock."""

    def setUp(self):
        self.root = _vault(self)

    def test_replaying_the_whole_act_writes_no_second_receipt(self):
        first = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)
        after_first = _files(self.root)
        second = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)

        self.assertEqual(second["era_id"], first["era_id"])
        self.assertEqual(len(_receipts(self.root)), 1)
        self.assertEqual(len(em.active_era_memberships(self.root)), 1)
        # The assertion id includes the `source_ref`, and the source is
        # content-addressed on the same words in the same turn — so the replay
        # lands on the same file and says it created nothing.
        self.assertEqual(
            second["steps"]["memberships"][0]["assertion_id"],
            first["steps"]["memberships"][0]["assertion_id"],
        )
        self.assertFalse(second["steps"]["memberships"][0]["created"])
        self.assertEqual(after_first, _files(self.root))

    def test_a_job_that_dies_before_the_memberships_leg_completes_on_retry(self):
        # T-W-02/03 with the crash point ON the leg this PR revives.
        partial = er.record_era(
            self.root, GRADUATION_PAYLOAD, now=NOW, stop_after="within"
        )
        self.assertNotIn("memberships", partial["steps"])
        self.assertEqual(_receipts(self.root), [])

        whole = er.record_era(self.root, GRADUATION_PAYLOAD, now=NOW)
        self.assertEqual(whole["era_id"], partial["era_id"])
        self.assertEqual(len(_receipts(self.root)), 1)
        self.assertTrue(whole["steps"]["memberships"][0]["created"])

        # And the vault converges on exactly the file set an uninterrupted run
        # produces — the property the whole atomic writer exists for.
        clean = _vault(self)
        er.record_era(clean, GRADUATION_PAYLOAD, now=NOW)
        self.assertEqual(_files(self.root), _files(clean))

    def test_a_job_that_dies_inside_the_leg_files_no_duplicate(self):
        # Two membership rows, and the retry re-runs BOTH: the first must land
        # on its existing file rather than a second one.
        payload = dict(GRADUATION_PAYLOAD)
        payload["memberships"] = [
            {"member_node_id": "event:graduation-2011"},
            {"member_node_id": "event:move-out-2011"},
        ]
        em.file_era_membership(
            self.root,
            member_node_id="event:graduation-2011",
            era_node_id=ei.era_id_for(ei.turn_operation_id("s1", "t1")),
            source_ref=ts.promote_conversational_source(
                self.root, payload["message_text"],
                {"session_ref": "s1", "turn_ref": "t1", "occurred_at": NOW},
            ),
            relation="within",
            basis=er.MEMBERSHIP_DEFAULT_BASIS,
            occurred_at=NOW,
        )
        self.assertEqual(len(_receipts(self.root)), 1)

        summary = er.record_era(self.root, payload, now=NOW)
        self.assertEqual(len(_receipts(self.root)), 2)
        created = [row["created"] for row in summary["steps"]["memberships"]]
        self.assertEqual(created, [False, True])


# --------------------------------------------------------------------------
# The class guard
# --------------------------------------------------------------------------


#: Lazy imports inside `system/*.py` that are neither siblings nor stdlib.
#: Named, not inferred: an optional third-party dependency is a legitimate
#: lazy import, and a NEW name appearing here should be a deliberate edit
#: rather than something the guard quietly tolerates.
EXTERNAL_LAZY_IMPORTS = frozenset({"anthropic"})


def _lazy_imports(path: Path):
    """Every module name imported inside a function body of one file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Import):
                for alias in sub.names:
                    yield sub.lineno, alias.name.split(".")[0]
            elif isinstance(sub, ast.ImportFrom) and sub.level == 0 and sub.module:
                yield sub.lineno, sub.module.split(".")[0]


class LazyImportNamesResolveTests(unittest.TestCase):
    """A seam resolved by a STRING needs a test that the string names something.

    The defect this file exists for was invisible for a release because the
    only thing that knew `era_membership` was wrong was an `ImportError` the
    seam deliberately swallowed. Nothing else — not mypy, not ruff, not a
    single test — reads a lazily-imported module name. This does.
    """

    def _resolvable(self) -> set[str]:
        names = {path.stem for path in (ROOT / "system").glob("*.py")}
        names |= {path.name for path in (ROOT / "system").iterdir() if path.is_dir()}
        names |= {path.stem for path in ROOT.glob("*.py")}
        names |= set(sys.stdlib_module_names)
        return names | EXTERNAL_LAZY_IMPORTS

    def test_era_record_lazily_imports_only_modules_that_exist(self):
        known = self._resolvable()
        unknown = [
            f"era_record.py:{line} import {name}"
            for line, name in _lazy_imports(ROOT / "system" / "era_record.py")
            if name not in known
        ]
        self.assertEqual(unknown, [])

    def test_every_lazy_import_in_system_names_a_module_that_exists(self):
        known = self._resolvable()
        unknown = [
            f"{path.name}:{line} import {name}"
            for path in sorted((ROOT / "system").glob("*.py"))
            for line, name in _lazy_imports(path)
            if name not in known
        ]
        self.assertEqual(unknown, [])

    def test_the_guard_fires_on_a_name_that_does_not_exist(self):
        # A guard proven-to-fire beats a guard asserted. This is the base
        # revision's exact line, checked against the same resolver.
        self.assertNotIn("era_membership", self._resolvable())
        self.assertIn("era_memberships", self._resolvable())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
