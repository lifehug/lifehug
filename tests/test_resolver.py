"""The resolver: answer "when?" from the vault, with citations, and file it.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
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


class LegsTests(unittest.TestCase):
    """The two legs a host runs: a plan it buys, an envelope it hands back.

    One synthetic vault with real receipts and a real published projection, so
    the plan is built from the same targets the local run reads.
    """

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="resolver-legs-")
        (self.root / "answers").mkdir(parents=True)
        (self.root / "state" / "temporal_claims").mkdir(parents=True)
        self.nodes: dict[str, str] = {}
        self.handles: dict[str, str] = {}

    def story(self, stem: str, body: str, moments: list[tuple[str, str, list[str]]]) -> None:
        """One story file plus one raw handle claim per unplaced moment."""
        (self.root / "answers" / f"{stem}.md").write_text(
            f"---\ntitle: {stem}\ntype: prompted_answer\n---\n\n{body}\n", "utf-8")
        for label, relation, anchors in moments:
            node_id = tp.derive_node_id(node_kind="event", event_kind="moment",
                                        subject_refs=["self"], discriminator=f"{stem}-{label}")
            claim = tc.validate_temporal_claim({
                "source_kind": "import", "claim_type": "relative_order", "subject_mention": "self",
                "event_kind": "moment", "event_ref": node_id, "event_mention": label,
                "temporal_value": {"relation": relation, "anchors": list(anchors)},
                "evidence": [{"quote": anchors[0]}], "basis": "explicit", "confidence": 0.8,
                "extractor_version": "classifier-claims/rule:4",
                "source_ref": {"source_id": f"classification:answers-{stem}#{label}",
                               "revision": "sha256:" + "1" * 64,
                               "source_path": f"answers/{stem}.md"},
            }, now=NOW)
            ts.write_receipt(self.root, {"source_ref": claim["source_ref"],
                                         "extractor_version": "classifier-claims/rule:4",
                                         "claims": [claim]}, now=NOW)
            self.nodes[label] = node_id
            self.handles[label] = claim["claim_id"]

    def publish(self):
        import temporal_publication as pub

        return pub.publish(self.root, now=NOW)

    def answer_text(self, *labels: str, question: str = "") -> str:
        rows = []
        for label in labels:
            rows.append({
                "node_id": self.nodes[label],
                "answer": None if question else {"earliest": "1996-06", "latest": "1996-06"},
                "basis": "stated", "confidence": 0.9, "fact_key": "cedarport_move",
                "citations": [] if question else [{"doc": "story", "quote": "moved to Cedarport in June 1996"}],
                "reason": "The story says so.", "question": question or None, "also_resolves": [],
            })
        return json.dumps({"answers": rows})

    def envelope(self, item: dict, text: str, **overrides) -> dict:
        row = {**{k: item[k] for k in ("key", "source_path", "node_ids", "identity")},
               "text": text, "usage": {"input_tokens": 7, "output_tokens": 3, "stop_reason": "end_turn"},
               "truncated": False}
        row.update(overrides)
        return {"schema_version": 1, "model": "test-model", "items": [row]}

    # -- leg A ------------------------------------------------------------

    def test_the_plan_is_one_item_per_story_with_its_prompt_and_identity(self):
        self.story("a1", "We moved to Cedarport in June 1996 and the shop opened after.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        plan = resolver.plan_items(self.root, limit=5)
        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(plan["extractor_version"], resolver.EXTRACTOR_VERSION)
        self.assertEqual(plan["model_hint"], resolver.DEFAULT_MODEL)
        self.assertEqual(plan["max_output_tokens"], 16000)
        self.assertEqual(plan["pending_sources"], 1)
        self.assertEqual(plan["pending_events"], 1)
        self.assertEqual(plan["deterministic_pending"], 0)
        self.assertTrue(plan["complete"])
        self.assertEqual(len(plan["items"]), 1)
        item = plan["items"][0]
        self.assertEqual(sorted(item), ["identity", "key", "node_ids", "prompt", "source_path"])
        self.assertEqual(item["source_path"], "answers/a1.md")
        self.assertEqual(item["node_ids"], [self.nodes["shop"]])
        self.assertRegex(item["key"], r"^[0-9a-f]{32}$")
        self.assertIn(self.nodes["shop"], item["prompt"])
        self.assertEqual(sorted(item["identity"]), ["source_sha256", "spine_digest", "targets_digest"])
        self.assertRegex(item["identity"]["source_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(item["identity"]["spine_digest"].startswith("sha256:"))

    def test_the_plan_writes_nothing_under_the_vault(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in sorted(self.root.rglob("*")) if p.is_file()}
        resolver.plan_items(self.root, limit=5)
        after = {p.relative_to(self.root).as_posix(): p.read_bytes()
                 for p in sorted(self.root.rglob("*")) if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / resolver.LEDGER_RELATIVE).exists())

    def test_a_named_source_is_planned_first(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.story("b2", "The picnic happened after the shop opened.",
                   [("picnic", "after", ["the shop opening"])])
        self.publish()
        default = resolver.plan_items(self.root, limit=1)["items"][0]
        self.assertEqual(default["source_path"], "answers/a1.md")
        named = resolver.plan_items(self.root, limit=1, only_sources={"answers/b2.md"})["items"][0]
        self.assertEqual(named["source_path"], "answers/b2.md")
        # A name is an ORDER for a plan, not a filter: the other story is still
        # counted as pending, which is how the host knows to loop again.
        self.assertFalse(resolver.plan_items(self.root, limit=1,
                                             only_sources={"answers/b2.md"})["complete"])

    def test_a_bare_age_handle_is_counted_but_never_planned(self):
        self.story("a1", "I was eighteen when the shop opened.", [("shop", "within", ["18"])])
        self.publish()
        plan = resolver.plan_items(self.root, limit=5)
        # No birth date on this synthetic spine, so the age table cannot answer
        # it and the model must: the handle is planned, not deterministic.
        self.assertEqual(plan["deterministic_pending"], 0)
        self.assertEqual(plan["pending_events"], 1)

    def test_unanswered_rows_are_replanned_in_chunks_of_four(self):
        self.story("a1", "Five moments, none of them dated.",
                   [(f"m{n}", "after", ["the move to Cedarport"]) for n in range(5)])
        self.publish()
        ledger = {"version": 1, "nodes": {
            node_id: {"label": label, "source_path": "answers/a1.md", "model": "test-model",
                      "at": NOW, "status": "no_answer_returned", "attempts": 1}
            for label, node_id in self.nodes.items()}}
        resolver.save_ledger(self.root, ledger)
        plan = resolver.plan_items(self.root, limit=10)
        self.assertEqual([len(item["node_ids"]) for item in plan["items"]], [4, 1])
        self.assertEqual(plan["pending_events"], 5)
        # Twice is enough: a row that came back empty two rounds running is not
        # bought a third time without --retry-failed.
        for row in ledger["nodes"].values():
            row["attempts"] = 2
        resolver.save_ledger(self.root, ledger)
        self.assertEqual(resolver.plan_items(self.root, limit=10)["items"], [])
        self.assertEqual(len(resolver.plan_items(self.root, limit=10, retry_failed=True)["items"]), 2)

    def test_a_settled_moment_is_never_planned_again(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        for status in ("resolved", "unknown"):
            with self.subTest(status=status):
                resolver.save_ledger(self.root, {"version": 1, "nodes": {
                    self.nodes["shop"]: {"status": status, "at": NOW, "source_path": "answers/a1.md"}}})
                plan = resolver.plan_items(self.root, limit=5)
                self.assertEqual(plan["items"], [])
                self.assertEqual(plan["pending_events"], 0)
                self.assertTrue(plan["complete"])

    def test_a_plan_inside_the_vault_is_refused_and_outside_is_written(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        plan = resolver.plan_items(self.root, limit=5)
        with self.assertRaises(ValueError):
            resolver.write_plan(plan, self.root / "state" / "plan.json", vault_root=self.root)
        outside = root_parent_tmp(self, ROOT, prefix="resolver-out-") / "plan.json"
        written = resolver.write_plan(plan, outside, vault_root=self.root)
        self.assertEqual(json.loads(written.read_text("utf-8")), plan)

    # -- leg C ------------------------------------------------------------

    def test_filing_an_envelope_files_the_claim_and_retires_the_handle(self):
        self.story("a1", "We moved to Cedarport in June 1996; the shop opened that month.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        report = resolver.file_envelope(self.root, self.envelope(item, self.answer_text("shop")),
                                        now=NOW)
        self.assertEqual(report["filed"], 1)
        self.assertEqual(report["outcomes"], {"resolved": 1})
        self.assertEqual(report["bases"], {"stated": 1})
        self.assertEqual(report["refused_items"], [])
        self.assertEqual(report["usage"], {"input_tokens": 7, "output_tokens": 3})
        self.assertEqual(report["remaining_events"], 0)
        self.assertTrue(report["complete"])
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.root)["claims"]}
        self.assertEqual(by_id[self.handles["shop"]]["status"], "superseded")
        filed = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(filed["status"], "resolved")
        self.assertEqual(filed["model"], "test-model")
        mine = by_id[filed["claim_id"]]
        self.assertEqual(mine["extractor_version"], resolver.EXTRACTOR_VERSION)
        self.assertEqual(mine["temporal_value"]["basis"], "stated")

    def test_an_unknown_answer_keeps_its_question_and_files_nothing(self):
        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        report = resolver.file_envelope(
            self.root, self.envelope(item, self.answer_text("shop", question="Which year did the shop open?")),
            now=NOW)
        self.assertEqual(report["filed"], 0)
        self.assertEqual(report["outcomes"], {"unknown": 1})
        self.assertEqual(report["open_questions"][0]["question"], "Which year did the shop open?")

    def test_a_story_edited_under_the_plan_refuses_its_answer(self):
        self.story("a1", "We moved to Cedarport in June 1996; the shop opened that month.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        (self.root / "answers" / "a1.md").write_text(
            "---\ntitle: a1\n---\n\nActually the shop opened long before the move.\n", "utf-8")
        report = resolver.file_envelope(self.root, self.envelope(item, self.answer_text("shop")), now=NOW)
        self.assertEqual(report["filed"], 0)
        self.assertEqual(report["refused_items"], [{"key": item["key"], "reason": "stale_source"}])
        self.assertEqual(resolver.load_ledger(self.root)["nodes"], {})

    def test_moments_that_moved_under_the_plan_refuse_their_answer(self):
        self.story("a1", "We moved to Cedarport in June 1996; the shop opened that month.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = dict(resolver.plan_items(self.root, limit=5)["items"][0])
        item["identity"] = {**item["identity"], "targets_digest": "sha256:" + "0" * 64}
        report = resolver.file_envelope(self.root, self.envelope(item, self.answer_text("shop")), now=NOW)
        self.assertEqual(report["refused_items"], [{"key": item["key"], "reason": "stale_targets"}])
        self.assertEqual(report["filed"], 0)

    def test_a_moved_spine_is_a_note_on_the_entry_not_a_refusal(self):
        self.story("a1", "We moved to Cedarport in June 1996; the shop opened that month.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = dict(resolver.plan_items(self.root, limit=5)["items"][0])
        item["identity"] = {**item["identity"], "spine_digest": "sha256:" + "0" * 64}
        report = resolver.file_envelope(self.root, self.envelope(item, self.answer_text("shop")), now=NOW)
        self.assertEqual(report["filed"], 1)
        self.assertEqual(report["refused_items"], [])
        self.assertTrue(resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]["spine_changed"])

    def test_a_truncated_answer_counts_an_attempt_rather_than_filing(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        for expected in (1, 2):
            report = resolver.file_envelope(
                self.root, self.envelope(item, self.answer_text("shop"), truncated=True), now=NOW)
            self.assertEqual(report["filed"], 0)
            self.assertEqual(report["outcomes"], {"no_answer_returned": 1})
            entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
            self.assertEqual(entry["status"], "no_answer_returned")
            self.assertEqual(entry["attempts"], expected)
        self.assertEqual(resolver.plan_items(self.root, limit=5)["items"], [])

    def test_filing_the_same_envelope_twice_files_nothing_the_second_time(self):
        self.story("a1", "We moved to Cedarport in June 1996; the shop opened that month.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        envelope = self.envelope(item, self.answer_text("shop"))
        self.assertEqual(resolver.file_envelope(self.root, envelope, now=NOW)["filed"], 1)
        receipts = sorted(p.name for p in (self.root / "state" / "temporal_claims").rglob("*.json"))
        replay = resolver.file_envelope(self.root, envelope, now="2026-09-02T12:00:00Z")
        self.assertEqual(replay["filed"], 0)
        self.assertEqual([row["reason"] for row in replay["refused_items"]], ["stale_targets"])
        self.assertEqual(sorted(p.name for p in (self.root / "state" / "temporal_claims").rglob("*.json")),
                         receipts)

    def test_an_envelope_that_is_not_one_is_refused_before_anything_is_written(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        for bad in (None, [], {"model": "x"}, {"items": "no"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolver.file_envelope(self.root, bad, now=NOW)
        self.assertFalse((self.root / resolver.LEDGER_RELATIVE).exists())

    # -- the legs composed ------------------------------------------------

    def test_the_local_run_files_what_the_two_legs_file(self):
        self.story("a1", "We moved to Cedarport in June 1996; the shop opened that month.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        text = self.answer_text("shop")
        with mock.patch.object(resolver, "make_completer",
                               return_value=lambda prompt, key: (text, {"output_tokens": 5})):
            report = resolver.resolve_vault(self.root, model="test-model", execute=True, limit=20,
                                            concurrency=1, only_sources=None, force=False, now=NOW)
        self.assertEqual(report["filed"], 1)
        self.assertEqual(report["outcomes"], {"resolved": 1})
        self.assertEqual(report["bases"], {"stated": 1})
        self.assertEqual(report["events_pending"], 1)
        self.assertEqual(report["round1_missing"], 0)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], "resolved")
        self.assertEqual(entry["basis"], "stated")
        # The purchase is durable, and a second run buys nothing and files
        # nothing: the ledger already says this moment is settled.
        self.assertTrue(list((self.root / resolver.RESPONSES_RELATIVE).glob("*.json")))

        def never(prompt, key):
            raise AssertionError("a settled moment was bought again")

        with mock.patch.object(resolver, "make_completer", return_value=never):
            again = resolver.resolve_vault(self.root, model="test-model", execute=True, limit=20,
                                           concurrency=1, only_sources=None, force=False, now=NOW)
        self.assertEqual(again["filed"], 0)
        self.assertEqual(again["events_pending"], 0)

    def test_round_two_re_asks_only_the_moments_round_one_skipped(self):
        self.story("a1", "We moved to Cedarport in June 1996. Two moments hang off it.",
                   [("shop", "after", ["the move to Cedarport"]),
                    ("picnic", "after", ["the move to Cedarport"])])
        self.publish()
        asked: list[int] = []

        def completer(prompt, key):
            asked.append(sum(node in prompt for node in self.nodes.values()))
            # Round 1 answers only the shop; round 2 is asked the picnic alone.
            return self.answer_text("picnic" if len(asked) > 1 else "shop"), {}

        with mock.patch.object(resolver, "make_completer", return_value=completer):
            report = resolver.resolve_vault(self.root, model="test-model", execute=True, limit=20,
                                            concurrency=1, only_sources=None, force=False, now=NOW)
        self.assertEqual(asked, [2, 1])
        self.assertEqual(report["round1_missing"], 1)
        self.assertEqual(report["filed"], 2)
        statuses = {node: resolver.load_ledger(self.root)["nodes"][node]["status"]
                    for node in self.nodes.values()}
        self.assertEqual(set(statuses.values()), {"resolved"})

    def test_a_moment_the_model_never_answers_is_remembered_with_its_attempts(self):
        self.story("a1", "One moment the model has nothing to say about.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        with mock.patch.object(resolver, "make_completer",
                               return_value=lambda prompt, key: ('{"answers": []}', {})):
            report = resolver.resolve_vault(self.root, model="test-model", execute=True, limit=20,
                                            concurrency=1, only_sources=None, force=False, now=NOW)
        self.assertEqual(report["filed"], 0)
        self.assertEqual(report["round1_missing"], 1)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], "no_answer_returned")
        self.assertEqual(entry["attempts"], 2)

    def test_a_dry_run_reports_the_first_plan_item_and_writes_nothing(self):
        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        report = resolver.resolve_vault(self.root, model="test-model", execute=False, limit=20,
                                        concurrency=1, only_sources=None, force=False, now=NOW)
        self.assertEqual(report["sources_pending"], 1)
        self.assertEqual(report["events_pending"], 1)
        self.assertEqual(report["sample_source"], "answers/a1.md")
        self.assertGreater(report["sample_prompt_chars"], 0)
        self.assertFalse((self.root / resolver.LEDGER_RELATIVE).exists())

    # -- the question on the card -----------------------------------------

    def test_a_work_item_asks_the_resolvers_own_question(self):
        import temporal_publication as pub

        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        generic = {row.get("node_ref"): row.get("prompt_intent")
                   for row in (pub.read_work_items(self.root) or {})["work_items"]}
        self.assertIn("shop", str(generic[self.nodes["shop"]]))
        self.assertNotIn("summer", str(generic[self.nodes["shop"]]))
        resolver.save_ledger(self.root, {"version": 1, "nodes": {self.nodes["shop"]: {
            "label": "The shop", "source_path": "answers/a1.md", "status": "unknown",
            "question": "Which summer did the shop open?", "at": NOW}}})
        pub.publish(self.root, now="2026-09-02T12:00:00Z")
        rows = {row.get("node_ref"): row for row in (pub.read_work_items(self.root) or {})["work_items"]}
        mine = rows[self.nodes["shop"]]
        self.assertEqual(mine["prompt_intent"], "Which summer did the shop open?")
        self.assertEqual(mine["question_source"], "resolver")
        # A better sentence is not different arithmetic.
        self.assertEqual((pub.read_projection(self.root) or {})["calculation_rule_version"],
                         tt.CALCULATION_RULE_VERSION)
        # Every other item keeps the composer's sentence and says nothing about
        # where it came from.
        others = [row for node, row in rows.items() if node != self.nodes["shop"]]
        self.assertTrue(all("question_source" not in row for row in others))

    def test_a_resolved_moment_puts_no_question_on_any_card(self):
        import temporal_publication as pub

        self.story("a1", "The shop opened after the move to Cedarport.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        resolver.save_ledger(self.root, {"version": 1, "nodes": {self.nodes["shop"]: {
            "status": "resolved", "question": "never asked", "at": NOW}}})
        self.assertEqual(pub.resolver_questions(self.root), {})


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
