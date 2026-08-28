"""E0 — the four immediate Eras defects (contract `docs/pr-specs/eras-o-e0-immediate-defects.md`).

This file is shared by the two E0 branches: `O-E0b` (the owner's birth binds to
`self`) and `O-E0d` (`correct --supersedes`) live here; `O-E0a`/`O-E0c` add
their own cases alongside.

Every negative case below was run against unmodified `main` first and seen
failing — the point of the file is the failure it used to produce, not the
green it produces now.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tempdirs import root_parent_tmp  # noqa: E402

import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402


def load(name):
    """A private copy of `system/<name>.py`, leaving the shared module bound."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    original = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if original is not None:
            sys.modules[name] = original
        else:
            sys.modules.pop(name, None)
    return module


# ---------------------------------------------------------------------------
# O-E0b — the owner's birth binds to `self`
# ---------------------------------------------------------------------------


def _revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _claim(**overrides) -> dict:
    source = overrides.pop("source", "src-1")
    quote = overrides.pop("quote", "a sentence somebody said")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": _revision(source)},
        "evidence": [{"quote": quote}],
        "extractor_version": "listener:1",
        "created_at": "2026-08-26T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def _derive(*claims) -> dict:
    index = {"version": ts.INDEX_VERSION, "claims": [dict(c) for c in claims]}
    return tt.derive_calculated_timeline(index, now="2026-08-27T00:00:00Z").to_dict()


OWNER_BIRTH_LEGACY = dict(
    source="lm-birth",
    claim_type="date",
    subject_mention="birth",
    event_kind="birth",
    temporal_value="1981-07-11",
    quote="birth.date = \"1981-07-11\"",
)
OWNER_BIRTH_SELF = dict(
    source="lm-birth-live",
    claim_type="date",
    subject_mention="self",
    event_kind="birth",
    temporal_value="1981-07-11",
    quote="I was born on the eleventh of July, 1981",
)
CHILD_BIRTH = dict(
    source="lm-child",
    claim_type="date",
    subject_mention="Charlee",
    event_kind="birth",
    temporal_value="2010-12-21",
    quote="Charlee was born 21 December 2010",
)
OWNER_AGE = dict(
    source="msg-1",
    claim_type="age",
    subject_mention="self",
    event_kind="school",
    temporal_value="12",
    quote="when I was 12",
)


class OwnerBirthBindsToSelfTests(unittest.TestCase):
    """T-BO-01 / T-BO-01b — `04-context/birth_anchor_probe.py`, committed."""

    def _owner_birth_nodes(self, derived: dict) -> list[dict]:
        return [
            node
            for node in derived["nodes"]
            if node.get("event_kind") == "birth"
            and "self" in (node.get("subject_refs") or ())
        ]

    def test_bo_01_a_childs_birth_never_costs_the_owner_the_birth_anchor(self):
        """The executed probe: the second birth used to unseat the owner's own."""
        rows = [
            _claim(**OWNER_BIRTH_LEGACY),
            _claim(**CHILD_BIRTH),
            _claim(**OWNER_AGE),
        ]
        for label, ordering in (
            ("import order", rows),
            ("receipt order reversed", list(reversed(rows))),
        ):
            with self.subTest(ordering=label):
                derived = _derive(*ordering)
                text = str(derived)
                self.assertNotIn("age_without_birth_anchor", text)
                kinds = {
                    (item.get("kind"), item.get("requested_field"))
                    for item in derived.get("work_items") or ()
                }
                self.assertNotIn(("missing_anchor", "birth_date"), kinds)
                school = [n for n in derived["nodes"] if n.get("event_kind") == "school"]
                self.assertEqual(len(school), 1)
                best = (school[0].get("best_temporal_value") or {}).get("best")
                self.assertTrue(best, "the age claim must resolve against the birthday")
                self.assertTrue(str(best).startswith("199"))
                owner = self._owner_birth_nodes(derived)
                self.assertEqual(len(owner), 1, "the owner's birth is one node, subject `self`")

    def test_bo_01b_legacy_and_new_receipts_are_one_owner_birth(self):
        """An extraction-rule change never mints a second, contradictory birth."""
        legacy = _claim(**OWNER_BIRTH_LEGACY)
        live = _claim(**OWNER_BIRTH_SELF)
        for label, ordering in (
            ("legacy first", (legacy, live)),
            ("live first", (live, legacy)),
        ):
            with self.subTest(ordering=label):
                derived = _derive(*ordering)
                births = [n for n in derived["nodes"] if n.get("event_kind") == "birth"]
                self.assertEqual(len(births), 1, "two receipts, one owner birth")
                node = births[0]
                self.assertEqual(node.get("subject_refs"), ["self"])
                self.assertEqual(node.get("conflict_state"), "none")
                self.assertEqual(
                    (node.get("best_temporal_value") or {}).get("best"), "1981-07-11"
                )
                self.assertEqual(len(node.get("input_claim_refs") or ()), 2)

    def test_bo_01c_the_legacy_mention_resolves_through_a_recorded_rule(self):
        """Never a silent rewrite: the mapping is a reversible ResolutionRecord."""
        import identity_resolution as ident

        resolved, records, _ = tt._resolve_subjects(
            [_claim(**OWNER_BIRTH_LEGACY)],
            resolution_records=(),
            roster_snapshot=(),
            now="2026-08-27T00:00:00Z",
        )
        self.assertEqual(resolved[0].get("subject_ref"), tt.DEFAULT_OWNER_REF)
        self.assertEqual(resolved[0].get("subject_mention"), "birth", "the receipt is untouched")
        record = records[tc.normalized_mention_key("birth")]
        self.assertEqual(record.resolution, "same")
        self.assertEqual(record.resolved_ref, tt.DEFAULT_OWNER_REF)
        self.assertEqual(record.reason, ident.OWNER_BIRTH_DOMAIN_REASON)
        self.assertTrue(record.reversible)

    def test_bo_01d_an_owner_verdict_still_beats_the_rule(self):
        """Layer 2 is unchanged — a supplied record wins over the deterministic rung."""
        import identity_resolution as ident

        supplied = ident.resolution_record(
            {
                "mention": "birth",
                "candidates": [{"ref": "person/somebody-else", "basis": "name"}],
                "resolution": "same",
                "resolved_ref": "person/somebody-else",
                "reason": ident.OWNER_REASON,
                "evidence_ref": "owner:test",
                "created_at": "2026-08-27T00:00:00Z",
            }
        )
        resolved, _, _ = tt._resolve_subjects(
            [_claim(**OWNER_BIRTH_LEGACY)],
            resolution_records=(supplied,),
            roster_snapshot=(),
            now="2026-08-27T00:00:00Z",
        )
        self.assertEqual(resolved[0].get("subject_ref"), "person/somebody-else")

    def test_bo_01e_a_non_birth_claim_mentioning_birth_is_untouched(self):
        """The rule is `event_kind == birth`, not the word wherever it appears."""
        odd = _claim(
            source="msg-2",
            claim_type="date",
            subject_mention="birth",
            event_kind="school",
            temporal_value="1994",
        )
        resolved, _, _ = tt._resolve_subjects(
            [_claim(**OWNER_BIRTH_LEGACY), odd],
            resolution_records=(),
            roster_snapshot=(),
            now="2026-08-27T00:00:00Z",
        )
        by_kind = {claim["event_kind"]: claim for claim in resolved}
        self.assertEqual(by_kind["birth"].get("subject_ref"), tt.DEFAULT_OWNER_REF)
        self.assertIsNone(by_kind["school"].get("subject_ref"))


class EntrySubjectMentionTests(unittest.TestCase):
    """T-E0-05 — `birth` mints `self`; every other domain is byte-identical."""

    def setUp(self):
        self.rows = {row["domain"]: row for row in li.load_questions()}

    def test_e0_05_birth_mints_self_and_no_other_domain_moves(self):
        self.assertIn("birth", self.rows)
        for domain, row in sorted(self.rows.items()):
            with self.subTest(domain=domain, entry="names nobody"):
                minted = lp.entry_subject_mention({"date": "1981"}, row, domain)
                self.assertEqual(minted, "self" if domain == "birth" else domain)
            with self.subTest(domain=domain, entry="names somebody"):
                named = lp.entry_subject_mention({"label": "Nana"}, row, domain)
                self.assertEqual(named, "self" if domain == "birth" else "Nana")

    def test_e0_05b_a_birth_entry_projects_claims_about_self(self):
        claims = lp.entry_claims(
            "birth",
            {"date": "1981-07-11", "date_basis": "stated"},
            source_ref={"source_id": "landmark:birth", "revision": _revision("landmark:birth")},
        )
        self.assertTrue(claims)
        self.assertEqual({c["subject_mention"] for c in claims}, {"self"})
        dated = [c for c in claims if c["claim_type"] == "date"]
        self.assertEqual([c["event_kind"] for c in dated], ["birth"])


# ---------------------------------------------------------------------------
# O-E0d — a correction can be corrected
# ---------------------------------------------------------------------------


ANSWER_TEXT = (
    '---\ntitle: "Question A1"\nsource_id: "answer:A1"\ntype: "prompted_answer"\n'
    "---\n\n# Question A1\n\nCharlee wrote me a letter when I was a boy.\n"
)
OTHER_ANSWER_TEXT = (
    '---\ntitle: "Question A2"\nsource_id: "answer:A2"\ntype: "prompted_answer"\n'
    "---\n\n# Question A2\n\nSomething else entirely.\n"
)


class SupersedingCorrectionTests(unittest.TestCase):
    """T-E0-08…T-E0-12 — the E7a unblocker."""

    def setUp(self):
        self.si = load("source_integrity")
        self.root = root_parent_tmp(self, ROOT, prefix="eras-e0-")
        self.answers = self.root / "answers"
        self.corrections = self.root / "sources" / "corrections"
        self.classifications = self.root / "state" / "classifications"
        self.answers.mkdir(parents=True)
        self.corrections.mkdir(parents=True)
        (self.answers / "A1.md").write_text(ANSWER_TEXT, encoding="utf-8")
        (self.answers / "A2.md").write_text(OTHER_ANSWER_TEXT, encoding="utf-8")
        self._patches = [
            mock.patch.object(self.si, "REPO_DIR", self.root),
            mock.patch.object(self.si, "ANSWERS_DIR", self.answers),
            mock.patch.object(self.si, "SOURCES_DIR", self.root / "sources"),
            mock.patch.object(self.si, "CORRECTION_SOURCES_DIR", self.corrections),
            mock.patch.object(self.si, "SOURCE_MANIFEST_FILE", self.root / "state" / "source_manifest.json"),
            mock.patch.object(self.si, "WIKI_DIR", self.root / "wiki"),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

    # -- helpers ---------------------------------------------------------

    def _correct(self, target, body, *, supersedes=None, kind="factual"):
        args = SimpleNamespace(
            target=target, kind=kind, source="manual", title=None, supersedes=supersedes
        )
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(body)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.si.cmd_correct(args)
        return code, out.getvalue(), err.getvalue()

    def _bodies(self, target="answers/A1.md"):
        return [
            record.body
            for record in self.si.active_corrections_for(
                self.root / target,
                corrections_dir=self.corrections,
                repo_dir=self.root,
            )
        ]

    def _correction_paths(self):
        return sorted(self.corrections.glob("*.md"))

    # -- the flag exists -------------------------------------------------

    def test_e0_08_supersedes_is_recorded_and_the_predecessor_is_untouched(self):
        code, _, err = self._correct("answers/A1.md", "It happened in my Childhood.")
        self.assertEqual(code, 0, err)
        first = self._correction_paths()[0]
        before = first.read_bytes()
        first_id = self.si.split_frontmatter(first.read_text(encoding="utf-8"))[0]["source_id"]

        code, _, err = self._correct(
            "answers/A1.md", "It happened around May 2022.", supersedes=first_id
        )
        self.assertEqual(code, 0, err)
        second = [p for p in self._correction_paths() if p != first][0]
        metadata, _ = self.si.split_frontmatter(second.read_text(encoding="utf-8"))
        self.assertEqual(metadata["supersedes"], first_id)
        self.assertEqual(metadata["supersedes_path"], self.si.rel(first))
        self.assertEqual(first.read_bytes(), before, "the predecessor is immutable")

    def test_e0_08b_the_target_classification_is_marked_stale(self):
        self.classifications.mkdir(parents=True)
        marked: list[tuple] = []

        class _Stub:
            @staticmethod
            def mark_stale(path, reason=""):
                marked.append((Path(path).name, reason))
                return True

        with mock.patch.dict(sys.modules, {"classify_story": _Stub}):
            code, _, err = self._correct("answers/A1.md", "It happened in my Childhood.")
            self.assertEqual(code, 0, err)
            first_id = self.si.split_frontmatter(
                self._correction_paths()[0].read_text(encoding="utf-8")
            )[0]["source_id"]
            code, _, err = self._correct(
                "answers/A1.md", "It happened around May 2022.", supersedes=first_id
            )
            self.assertEqual(code, 0, err)
        self.assertEqual([name for name, _ in marked], ["A1.md", "A1.md"])

    def test_e0_09_only_the_leaves_reach_a_reader(self):
        self._correct("answers/A1.md", "It happened in my Childhood.")
        first_id = self.si.split_frontmatter(
            self._correction_paths()[0].read_text(encoding="utf-8")
        )[0]["source_id"]
        self._correct("answers/A1.md", "It happened around May 2022.", supersedes=first_id)
        bodies = self._bodies()
        self.assertEqual(bodies, ["It happened around May 2022."])

    def test_e0_09b_a_chain_of_three_keeps_only_the_last(self):
        self._correct("answers/A1.md", "one")
        first_id = self.si.split_frontmatter(
            self._correction_paths()[0].read_text(encoding="utf-8")
        )[0]["source_id"]
        self._correct("answers/A1.md", "two", supersedes=first_id)
        second = [p for p in self._correction_paths()
                  if self.si.split_frontmatter(p.read_text(encoding="utf-8"))[0].get("supersedes")]
        second_id = self.si.split_frontmatter(second[0].read_text(encoding="utf-8"))[0]["source_id"]
        self._correct("answers/A1.md", "three", supersedes=second_id)
        self.assertEqual(self._bodies(), ["three"])

    def test_e0_09c_the_superseded_text_never_reaches_the_classify_prompt(self):
        cls = load("classify_story")
        self._correct("answers/A1.md", "It happened in my Childhood.")
        first_id = self.si.split_frontmatter(
            self._correction_paths()[0].read_text(encoding="utf-8")
        )[0]["source_id"]
        self._correct("answers/A1.md", "It happened around May 2022.", supersedes=first_id)
        with mock.patch.object(cls, "SOURCES_DIR", self.root / "sources"), \
                mock.patch.object(cls, "REPO_DIR", self.root):
            bodies = cls.corrections_for(self.answers / "A1.md")
            block = cls._corrections_block(self.answers / "A1.md")
        self.assertEqual(bodies, ["It happened around May 2022."])
        self.assertIn("around May 2022", block)
        self.assertNotIn("Childhood", block)

    def test_e0_10_supersedes_must_name_a_correction_of_the_same_target(self):
        self._correct("answers/A2.md", "a correction of a different source")
        other_id = self.si.split_frontmatter(
            self._correction_paths()[0].read_text(encoding="utf-8")
        )[0]["source_id"]
        code, _, err = self._correct("answers/A1.md", "new text", supersedes=other_id)
        self.assertEqual(code, 1)
        self.assertIn("supersedes_target_mismatch", err)

    def test_e0_10b_supersedes_must_name_a_correction(self):
        stray = self.corrections / "2026-01-01-not-a-correction.md"
        stray.write_text(
            '---\ntitle: "Reflection"\ntype: "source_reflection"\n'
            'source_id: "reflection:stray"\nreflects: "answer:A1"\n---\n\n# R\n\nbody\n',
            encoding="utf-8",
        )
        code, _, err = self._correct("answers/A1.md", "new text", supersedes="reflection:stray")
        self.assertEqual(code, 1)
        self.assertIn("supersedes_not_a_correction", err)

    def test_e0_10c_supersedes_must_name_something_that_exists(self):
        code, _, err = self._correct(
            "answers/A1.md", "new text", supersedes="correction:nobody-home"
        )
        self.assertEqual(code, 1)
        self.assertIn("supersedes_missing", err)
        self.assertEqual(self._correction_paths(), [], "nothing is written on a refusal")

    def test_e0_11_a_cycle_is_loud(self):
        self._correct("answers/A1.md", "one")
        first = self._correction_paths()[0]
        first_meta = self.si.split_frontmatter(first.read_text(encoding="utf-8"))[0]
        self._correct("answers/A1.md", "two", supersedes=first_meta["source_id"])
        second = [p for p in self._correction_paths() if p != first][0]
        second_meta = self.si.split_frontmatter(second.read_text(encoding="utf-8"))[0]
        # Hand-corrupt the predecessor into a cycle — the shape a bad merge makes.
        text = first.read_text(encoding="utf-8")
        first.write_text(
            text.replace(
                'correction_kind:',
                f'supersedes: "{second_meta["source_id"]}"\ncorrection_kind:',
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as caught:
            self._bodies()
        self.assertIn("supersedes_cycle", str(caught.exception))

    def test_e0_11b_an_edge_out_of_the_targets_set_is_loud(self):
        self._correct("answers/A1.md", "one")
        first = self._correction_paths()[0]
        text = first.read_text(encoding="utf-8")
        first.write_text(
            text.replace(
                "correction_kind:", 'supersedes: "correction:somewhere-else"\ncorrection_kind:', 1
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as caught:
            self._bodies()
        self.assertIn("supersedes_outside_target_set", str(caught.exception))

    def test_e0_09d_the_compiler_never_injects_a_superseded_correction(self):
        """The E7a step that matters: the wiki must stop asserting it too."""
        wc = load("wiki_compile")
        answers = {"A1": {"id": "A1", "source": "answers/A1.md", "body": "the story"}}
        corrections = [
            {
                "id": "correction:one",
                "source": "sources/corrections/one.md",
                "kind": "source_correction",
                "body": "It happened in my Childhood.",
                "corrects": "answer:A1",
                "corrects_path": "answers/A1.md",
                "supersedes": "",
                "supersedes_path": "",
            },
            {
                "id": "correction:two",
                "source": "sources/corrections/two.md",
                "kind": "source_correction",
                "body": "It happened around May 2022.",
                "corrects": "answer:A1",
                "corrects_path": "answers/A1.md",
                "supersedes": "correction:one",
                "supersedes_path": "sources/corrections/one.md",
            },
        ]
        self.assertEqual(
            [row["id"] for row in wc.active_corrections(corrections)], ["correction:two"]
        )
        applied = wc.apply_corrections(answers, {}, corrections)
        self.assertEqual(applied, 1)
        self.assertIn("around May 2022", answers["A1"]["body"])
        self.assertNotIn("Childhood", answers["A1"]["body"])

    def test_e0_09e_corrections_with_no_edge_compile_exactly_as_before(self):
        wc = load("wiki_compile")
        corrections = [
            {"id": "c1", "kind": "source_correction", "corrects": "answer:A1", "body": "a"},
            {"id": "c2", "kind": "source_correction", "corrects": "answer:A1", "body": "b"},
        ]
        self.assertEqual(wc.active_corrections(corrections), corrections)

    def test_e0_12_one_module_reads_the_corrections_directory(self):
        """T-E0-12 — the guard behind "one definition, many hosts".

        Semantic, not textual: an AST sweep for a `.glob`/`.rglob` whose
        RECEIVER is the corrections directory, in any module that also knows
        the `source_correction` type. Exactly one module may be both.
        """
        readers = set()
        for path in sorted(SYSTEM.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "source_correction" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in {"glob", "rglob"}:
                    continue
                if "correction" in ast.unparse(func.value).lower():
                    readers.add(path.name)
        self.assertEqual(readers, {"source_integrity.py"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
