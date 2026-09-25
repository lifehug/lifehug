"""v355 — a reader's name does not depend on which separator wrote it.

THE INCIDENT (lifehug#412, found by the hosting platform's acceptance suite
while pinning v354). v354 (lifehug#411) made the fold's receipt election key
on `temporal_claims.extractor_identity` — the reader's NAME, its VERSION
stripped — so two different readers of one message coexist and only the same
reader's later reading supersedes its own earlier one
(`temporal_store.A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`).
`extractor_identity` derived that name as
``text.split("/", 1)[0].split(":", 1)[0]``, which covers the two spellings
this package's own `extractor_version_string` produces:
``general_listener/schema:1/prompt:…/model:…`` and the older
``story-classifier:2``.

`lifehug-platform`'s acceptance substrate
(`services/api/tests/acceptance/substrate.py`) writes a third spelling this
package cannot produce but whose own contract test asserts against::

    EXTRACTOR        = "g2-acceptance@schema=1"
    NEWER_EXTRACTOR  = "g2-acceptance@schema=1;model=newer"

Its `test_a_newer_extractor_files_beside_the_old_one` ("O2 — re-extraction is
a new interpretation, never a cache rebuild") asserts the OLDER reading
becomes superseded — the same v354 rule, correctly applied, because both
strings name the SAME reader re-reading at a newer model. Under v354's
``/`` -then-``:`` split, neither string contains ``/`` or ``:`` before the
first ``@``/``;``, so both were read back whole and unequal — two different
readers, both staying active — and the platform's own test failed against a
package that claims to implement the rule it is testing.

The test's intent was right, and it matches v354's own rule ("a later
version of one reader still supersedes"). What was wrong is that a reader's
identity depended on which separator its writer happened to choose. The
owner's real vault only contains ``/``-separated versions (14 distinct
extractor versions on disk, none with ``@``), so this is not a data
migration — it is robustness the platform's stricter acceptance substrate
exposed first.

THE FIX. `temporal_claims.extractor_identity` now splits on the first
occurrence of ANY of ``/``, ``:``, ``@``, ``;`` or whitespace
(`temporal_claims.EXTRACTOR_NAME_SEPARATORS`) rather than only ``/`` then
only ``:``. A name never contains a separator —
`extractor_version_string`'s own label pass strips every one of these
characters out of a name before assembly — so this is one derivation with
one docstring, unchanged for every spelling v354 already covered, and now
also correct for a spelling this package never writes but a caller of its
public contract does.

GUARDS. Part 1 pins every spelling `extractor_identity` must resolve,
including the two platform strings resolving to the SAME identity. Part 2 is
a fold-level test, in `ManyReadersOneDocumentTests`'s own shape
(`test_v354_a_reading_is_only_superseded_by_the_same_reader.py`): two
receipts differing only in a ``;model=`` suffix supersede each other (same
reader, later version), while two genuinely different readers of the same
revision both stay active — the v354 property this change must not regress.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import general_listener as gl  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

#: The platform's own two constants (`lifehug-platform
#: services/api/tests/acceptance/substrate.py`), copied verbatim rather than
#: re-derived, because the whole point is that THESE bytes must resolve to
#: one identity.
PLATFORM_EXTRACTOR = "g2-acceptance@schema=1"
PLATFORM_NEWER_EXTRACTOR = "g2-acceptance@schema=1;model=newer"


class ExtractorIdentityOverEverySeparatorTests(unittest.TestCase):
    """`temporal_claims.extractor_identity` pinned over every spelling of
    "name, then a version" this package or its host writes."""

    def test_slash_schema_prompt_model_spelling(self):
        self.assertEqual(
            tc.extractor_identity(
                "general_listener/schema:1/prompt:9f2a/model:haiku"),
            "general_listener")

    def test_slash_rule_spelling(self):
        self.assertEqual(
            tc.extractor_identity("answer-placement/rule:1"), "answer-placement")

    def test_colon_rule_spelling(self):
        self.assertEqual(tc.extractor_identity("story-classifier:2"),
                         "story-classifier")

    def test_bare_name_with_no_version_at_all(self):
        self.assertEqual(tc.extractor_identity("era_record"), "era_record")

    def test_platform_at_sign_spelling(self):
        self.assertEqual(tc.extractor_identity(PLATFORM_EXTRACTOR),
                         "g2-acceptance")

    def test_platform_at_sign_with_semicolon_model_suffix(self):
        self.assertEqual(tc.extractor_identity(PLATFORM_NEWER_EXTRACTOR),
                         "g2-acceptance")

    def test_the_platforms_two_strings_are_the_same_reader(self):
        """This is the exact assertion the platform's own contract test needs:
        an older and a newer reading from `g2-acceptance` are ONE identity,
        so the fold can elect between them rather than treat them as two
        readers that both stay active."""
        self.assertEqual(tc.extractor_identity(PLATFORM_EXTRACTOR),
                         tc.extractor_identity(PLATFORM_NEWER_EXTRACTOR))

    def test_a_name_never_contains_a_separator_regardless_of_which_one(self):
        """Every spelling built through `extractor_version_string` is still
        covered: its label pass strips `/`, `:`, `@`, `;` and whitespace out
        of a name before assembly, so whichever separator appears first in
        the finished string is always the version boundary."""
        version = tc.extractor_version_string(
            "listener", schema_version=1, prompt_version="a1b2", model="opus")
        self.assertEqual(tc.extractor_identity(version), "listener")

    def test_a_version_with_no_name_is_still_refused(self):
        """v354's own guard, unchanged: whitespace-only collapses to empty and
        is refused before any separator search runs."""
        with self.assertRaises(tc.ExtractionReceiptError) as caught:
            tc.extractor_identity("   ")
        self.assertEqual(caught.exception.code, "extractor_version_required")

    def test_no_two_of_these_readers_share_an_identity(self):
        readers = {
            "general_listener": "general_listener/schema:1/prompt:9f2a/model:haiku",
            "answer-placement": "answer-placement/rule:1",
            "story-classifier": "story-classifier:2",
            "era_record": "era_record",
            "g2-acceptance": PLATFORM_EXTRACTOR,
        }
        self.assertEqual(
            len({tc.extractor_identity(v) for v in readers.values()}),
            len(readers))


class TheFoldOverASemicolonModelSuffixTests(unittest.TestCase):
    """The property v354 built, unregressed: same reader supersedes itself,
    different readers coexist — now proved for the platform's separator too.
    Fixture shape borrowed from `ManyReadersOneDocumentTests` in
    `test_v354_a_reading_is_only_superseded_by_the_same_reader.py`."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v355-separator-")
        for folder in ("state/temporal_claims", "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.ref = ts.promote_conversational_source(
            self.root, "Rosa and I married in 1978, the year I left Brindle.",
            {"session_ref": "s1", "turn_ref": "t1"})

    def file(self, version: str, *, best: str, created_at: str) -> Path:
        row = tc.validate_temporal_claim({
            "source_kind": "conversation",
            "source_ref": self.ref.to_dict(),
            "claim_type": "date",
            "subject_mention": "Rosa",
            "event_kind": "married",
            "temporal_value": {
                "best": best, "earliest": best, "latest": best,
                "granularity": "year", "confidence": "certain", "basis": "stated",
            },
            "evidence": [{"quote": "we married in 1978"}],
            "basis": "explicit",
            "confidence": 0.9,
            "extractor_version": version,
            "created_at": created_at,
        })
        return ts.write_receipt(self.root, {
            "source_ref": self.ref.to_dict(), "extractor_version": version,
            "created_at": created_at, "claims": [row],
        }, now=created_at)

    def index(self) -> dict:
        return ts.fold_active_index(self.root)

    def test_a_model_bump_in_the_semicolon_spelling_still_supersedes(self):
        """`g2-acceptance@schema=1` then `g2-acceptance@schema=1;model=newer`
        on the same revision: the platform's own O2 shape. Same reader, later
        version — the older reading is superseded, not left active beside it."""
        self.file(PLATFORM_EXTRACTOR, best="1977",
                  created_at="2026-08-20T10:00:00Z")
        self.file(PLATFORM_NEWER_EXTRACTOR, best="1978",
                  created_at="2026-08-26T10:00:00Z")
        counts = self.index()["counts"]
        self.assertEqual(counts["active"], 1)
        self.assertEqual(counts["superseded"], 1)
        self.assertEqual(counts["readings"], 1)
        active = ts.active_claims(self.index())[0]
        self.assertEqual(active["temporal_value"]["best"], "1978")

    def test_two_genuinely_different_readers_still_both_coexist(self):
        """The v354 property this change must not regress: a platform-style
        reader and this package's own listener, on the same revision, are two
        readers — both stay active."""
        self.file(PLATFORM_EXTRACTOR, best="1978",
                  created_at="2026-08-20T10:00:00Z")
        self.file(
            gl.claim_extractor_version(gl.claim_extractor(
                gl.LISTENER_EXTRACTOR, leaf="a leaf", model="haiku-class")),
            best="1978", created_at="2026-08-21T10:00:00Z")
        counts = self.index()["counts"]
        self.assertEqual(counts["active"], 2)
        self.assertEqual(counts["superseded"], 0)
        self.assertEqual(counts["readings"], 2)


if __name__ == "__main__":
    unittest.main()
