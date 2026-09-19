"""The resolver: answer "when?" from the vault, with citations, and file it.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"
BIRTH = "1984-03-09"


def spine(**overrides) -> dict:
    row = {"owner_name": "Pat Example", "birth": BIRTH,
           "stays": ["- Cedarport: June 1996–August 2001 [node:stay]"],
           "tenures": ["- Tidewheel Works: March 2002–September 2006 [node:job]"],
           "points": [], "people": [], "ages": resolver.age_table(BIRTH)}
    row.update(overrides)
    return row


class AgeArithmeticTests(unittest.TestCase):
    def test_the_age_table_is_computed_from_any_birth_date(self):
        table = resolver.age_table("2000-02-29")
        self.assertIn("4 -> 2004-02-29 to 2005-02-27", table)
        self.assertEqual(resolver.age_table("not a date"), [])

    def test_bare_age_handles_are_recognised_and_prose_is_not(self):
        for text, want in (("18", 18), ("at 16", 16), ("when I was 12", 12), ("age 7", 7),
                           ("early in my marriage", None), ("1985", None), ("18 months", None)):
            with self.subTest(text=text):
                self.assertEqual(resolver.age_from_handle(text), want)

    def test_age_range_honours_the_handles_relation(self):
        self.assertEqual(resolver.age_range(BIRTH, 18)["best"], "2002-03-09/2003-03-08")
        self.assertEqual(resolver.age_range(BIRTH, 18, "after")["best"], "2002-03-09/..")
        self.assertEqual(resolver.age_range(BIRTH, 18, "before")["best"], "../2003-03-08")


class VerificationTests(unittest.TestCase):
    passages = {"answers/a1.md#p0": {"doc_id": "answers/a1.md#p0", "path": "answers/a1.md",
                                     "text": "We moved to Cedarport in June 1996, right after the wedding."}}

    def item(self, **overrides) -> dict:
        row = {"node_id": "node:x", "answer": {"earliest": "1996-06", "latest": "1996-06"},
               "basis": "stated", "confidence": 0.9, "fact_key": "cedarport_move",
               "citations": [{"doc": "answers/a1.md#p0", "quote": "moved to Cedarport in June 1996"}],
               "reason": "The story says so."}
        row.update(overrides)
        return row

    def test_an_exact_citation_verifies(self):
        resolved, why = resolver.verify(self.item(), story="", passages=self.passages, sp=spine())
        self.assertEqual(why, "ok")
        self.assertEqual(resolved["record"]["best"], "1996-06")

    def test_punctuation_and_case_do_not_defeat_an_exact_quote(self):
        item = self.item(citations=[{"doc": "answers/a1.md#p0", "quote": "Moved to Cedarport in June 1996."}])
        self.assertEqual(resolver.verify(item, story="", passages=self.passages, sp=spine())[1], "ok")

    def test_a_spliced_quote_is_refused(self):
        item = self.item(citations=[{"doc": "answers/a1.md#p0", "quote": "moved to Cedarport in 1997 after the wedding"}])
        self.assertEqual(resolver.verify(item, story="", passages=self.passages, sp=spine())[1], "citations_unverified")

    def test_the_storys_own_paragraph_id_counts_as_the_story(self):
        item = self.item(citations=[{"doc": "answers/s1.md#p3", "quote": "the pipes froze that winter"}])
        resolved, why = resolver.verify(item, story="The pipes froze that winter.", passages={}, sp=spine(),
                                        story_path="answers/s1.md")
        self.assertEqual(why, "ok")

    def test_spine_facts_and_the_age_table_are_citable(self):
        item = self.item(basis="derived", citations=[{"doc": "spine", "quote": "18 -> 2002-03-09 to 2003-03-08"}],
                         answer={"earliest": "2002-03-09", "latest": "2003-03-08"})
        self.assertEqual(resolver.verify(item, story="", passages={}, sp=spine())[1], "ok")

    def test_bad_dates_and_reversed_ranges_are_refused(self):
        self.assertEqual(resolver.verify(self.item(answer={"earliest": "sometime", "latest": None}),
                                         story="", passages=self.passages, sp=spine())[1], "date_unparseable")
        self.assertEqual(resolver.verify(self.item(answer={"earliest": "1999", "latest": "1996"}),
                                         story="", passages=self.passages, sp=spine())[1], "range_reversed")

    def test_an_abstention_is_not_an_answer(self):
        self.assertEqual(resolver.verify(self.item(answer=None), story="", passages={}, sp=spine())[1], "no_answer")


class ParsingTests(unittest.TestCase):
    def test_answers_survive_fences_narration_and_code_in_strings(self):
        text = ('Thinking first {a: b}.\n```json\n{"answers": [{"node_id": "node:ab12".replace("ab","ab"), '
                '"answer": null, "basis": "inferred", "confidence": 0.1, "citations": [], "fact_key": "x", '
                '"reason": "r", "question": "When?", "also_resolves": []}]}\n```')
        rows = resolver.parse_answers(text)
        self.assertEqual([r["node_id"] for r in rows], ["node:ab12"])

    def test_garbage_is_no_rows_not_an_exception(self):
        self.assertEqual(resolver.parse_answers('{"answers": [ {"node_id": "node:1", "unterminated'), [])


class IndexTests(unittest.TestCase):
    def test_search_ranks_the_passage_that_holds_the_words(self):
        docs = [{"doc_id": "a#p0", "kind": "answer", "path": "a", "title": "a", "text": "The Tidewheel Works picnic by the river."},
                {"doc_id": "b#p0", "kind": "answer", "path": "b", "title": "b", "text": "A winter of frozen pipes in Millgate."}]
        found = resolver.Index(docs).search("Tidewheel picnic")
        self.assertEqual([d["doc_id"] for d in found], ["a#p0"])
        self.assertEqual(resolver.Index(docs).search("the and of"), [])


class FilingTests(unittest.TestCase):
    """A verified answer becomes a dated claim on the event's own node; the raw handle retires."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="resolver-")
        (self.root / "answers").mkdir(parents=True)
        (self.root / "state" / "temporal_claims").mkdir(parents=True)
        (self.root / "answers" / "a1.md").write_text(
            "---\ntitle: a1\ntype: prompted_answer\n---\n\nThe founding happened after the move to Cedarport.\n", "utf-8")
        self.event_ref = tp.derive_node_id(node_kind="event", event_kind="moment", subject_refs=["self"], discriminator="a1")
        handle = tc.validate_temporal_claim({
            "source_kind": "import", "claim_type": "relative_order", "subject_mention": "self",
            "event_kind": "moment", "event_ref": self.event_ref, "event_mention": "The founding",
            "temporal_value": {"relation": "after", "anchors": ["the move to Cedarport"]},
            "evidence": [{"quote": "after the move to Cedarport"}], "basis": "explicit", "confidence": 0.8,
            "extractor_version": "classifier-claims/rule:4",
            "source_ref": {"source_id": "classification:answers-a1#000000000001", "revision": "sha256:" + "1" * 64,
                           "source_path": "answers/a1.md"},
        }, now=NOW)
        ts.write_receipt(self.root, {"source_ref": handle["source_ref"], "extractor_version": "classifier-claims/rule:4",
                                     "claims": [handle]}, now=NOW)
        self.handle_id = handle["claim_id"]
        self.target = {"node_id": self.event_ref, "event_ref": self.event_ref, "label": "The founding",
                       "event_kind": "moment", "subject": "self", "event": {}, "handles": [
                           {"claim_id": self.handle_id, "relation": "after", "anchors": ["the move to Cedarport"]}],
                       "telling_ref": "classification:answers-a1#000000000001", "document_revision": None}

    def test_filing_adds_a_dated_claim_and_retires_the_handle(self):
        resolved = {"record": {"best": "1996-06/2001-08", "earliest": "1996-06", "latest": "2001-08",
                               "granularity": "range", "basis": "stated", "confidence": "certain",
                               "anchors": [], "provenance": []},
                    "basis": "inferred", "confidence": 0.5, "fact_key": "cedarport_stay",
                    "citations": [{"doc": "spine", "quote": "Cedarport: June 1996–August 2001"}], "reason": "During the stay."}
        filed = resolver.file_resolution(self.root, self.target, resolved, story_path="answers/a1.md",
                                         model="test-model", now=NOW, prior={})
        index = ts.fold_active_index(self.root)
        by_id = {c["claim_id"]: c for c in index["claims"]}
        self.assertEqual(by_id[self.handle_id]["status"], "superseded")
        mine = by_id[filed["claim_id"]]
        self.assertEqual(mine["status"], "active")
        self.assertEqual(mine["event_ref"], self.event_ref)
        self.assertEqual(mine["extractor_version"], resolver.EXTRACTOR_VERSION)
        self.assertEqual(mine["temporal_value"]["basis"], "anchor")
        self.assertEqual(mine["temporal_value"]["confidence"], "inferred")
        receipt = json.loads(Path(filed["receipt_path"]).read_text("utf-8"))
        self.assertEqual(receipt["extractor"]["telling_keys"], {filed["claim_id"]: "classification:answers-a1#000000000001"})

    def test_a_stated_answer_keeps_its_stated_basis(self):
        resolved = {"record": {"best": "1996-06", "earliest": "1996-06", "latest": "1996-06", "granularity": "month",
                               "basis": "stated", "confidence": "certain", "anchors": [], "provenance": []},
                    "basis": "stated", "confidence": 0.95, "fact_key": "move", "citations": [{"doc": "story", "quote": "move"}],
                    "reason": "Said so."}
        filed = resolver.file_resolution(self.root, self.target, resolved, story_path="answers/a1.md",
                                         model="test-model", now=NOW, prior={})
        mine = {c["claim_id"]: c for c in ts.fold_active_index(self.root)["claims"]}[filed["claim_id"]]
        self.assertEqual(mine["temporal_value"]["basis"], "stated")
        self.assertEqual(mine["basis"], "explicit")


class BatchHookTests(unittest.TestCase):
    """The resolver runs after each accepted batch and can never undo a filing."""

    def test_a_resolver_failure_is_reported_not_raised(self):
        import classification_refresh as cr
        from unittest import mock
        with mock.patch.object(resolver, "resolve_vault", side_effect=RuntimeError("no provider")):
            report = cr._resolve(Path("/nonexistent"), ["answers/a1.md"], model=None)
        self.assertEqual(report, {"error": "RuntimeError"})

    def test_no_accepted_sources_means_no_call(self):
        import classification_refresh as cr
        self.assertEqual(cr._resolve(Path("/nonexistent"), [], model=None), {"skipped": True})


if __name__ == "__main__":
    unittest.main()
