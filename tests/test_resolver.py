"""The resolver: answer "when?" from the vault, with citations, and file it.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Sequence
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_binder as eb  # noqa: E402
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

    def age_item(self, **overrides) -> dict:
        row = self.item(basis="derived", fact_key="age_21",
                        answer={"earliest": "2005-03-09", "latest": "2006-03-08"},
                        citations=[{"doc": "spine", "quote": "21 -> 2005-03-09 to 2006-03-08"}])
        row.update(overrides)
        return row

    def test_the_owners_age_table_never_answers_another_persons_age(self):
        """v324, `subject_age_not_owner`. "mom got married young, at 21" was
        dated 1979/1981 off the OWNER's birthday — a date for his mother's
        wedding computed from a fact about her son."""
        mom = {"subject": "Mom", "event": {}, "handles": []}
        self.assertEqual(
            resolver.verify(self.age_item(), story="", passages={}, sp=spine(), target=mom)[1],
            resolver.SUBJECT_AGE_NOT_OWNER)

    def test_the_owners_own_age_still_verifies(self):
        for subject in ("self", "narrator", "Pat Example"):
            with self.subTest(subject=subject):
                row = {"subject": subject, "event": {}, "handles": []}
                self.assertEqual(
                    resolver.verify(self.age_item(), story="", passages={}, sp=spine(), target=row)[1],
                    "ok")

    def test_a_relatives_moment_dated_from_the_story_is_untouched(self):
        """The refusal is about the age table, not about whose moment it is —
        a lived-through scene dated from the owner's own words still files."""
        row = {"subject": "Grandpa", "event": {}, "handles": []}
        resolved, why = resolver.verify(self.item(), story="", passages=self.passages,
                                        sp=spine(), target=row)
        self.assertEqual(why, "ok")
        self.assertIsNotNone(resolved)

    def test_a_target_is_optional_so_the_eval_lane_is_unchanged(self):
        self.assertEqual(resolver.verify(self.age_item(), story="", passages={}, sp=spine())[1], "ok")

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
            "extractor_version": "classifier-claims/rule:5",
            "source_ref": {"source_id": "classification:answers-a1#000000000001", "revision": "sha256:" + "1" * 64,
                           "source_path": "answers/a1.md"},
        }, now=NOW)
        ts.write_receipt(self.root, {"source_ref": handle["source_ref"], "extractor_version": "classifier-claims/rule:5",
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



class ReadingIsNotAnEventTests(unittest.TestCase):
    """v333 defect A. A resolver reading is another reading of ONE telling.

    Until this release the declaration was a best effort: `file_resolution`
    declared the telling only when `targets` had found one, and where it had
    not, `event_identity.telling_ref_for_claim` fell back to the claim's own
    source id — so the reading became a telling nobody shares, the fold gave it
    a node of its own, and the node it answered kept its card while the answer
    sat on a duplicate beside it.
    """

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="resolver-reading-")
        (self.root / "answers").mkdir(parents=True)
        (self.root / "state" / "temporal_claims").mkdir(parents=True)
        (self.root / "answers" / "q3.md").write_text(
            "---\ntitle: q3\ntype: prompted_answer\n---\n\nRowan's birth changed everything.\n", "utf-8")
        self.event_ref = tp.derive_node_id(node_kind="event", event_kind="moment",
                                           subject_refs=["self"], discriminator="q3")
        self.resolved = {
            "record": {"best": "2019-04-08", "earliest": "2019-04-08", "latest": "2019-04-08",
                       "granularity": "day", "basis": "stated", "confidence": "certain",
                       "anchors": [], "provenance": []},
            "basis": "stated", "confidence": 0.95, "fact_key": "rowan_birth",
            "citations": [{"doc": "story", "quote": "Rowan's birth"}], "reason": "Stated."}

    def target(self, **overrides) -> dict:
        row = {"node_id": "node:" + "a" * 24, "event_ref": self.event_ref,
               "label": "Rowan's birth as turning point", "event_kind": "moment",
               "subject": "self", "event": {}, "handles": [],
               "telling_ref": "", "document_revision": None}
        row.update(overrides)
        return row

    def test_the_reading_ref_names_the_event_ref_and_never_the_node_id(self):
        """Keyed on `event_ref`, because a telling folded into an episode is
        published under the EPISODE's node id while its claim names its own
        event — and `episode_binder.reads_node` wants exactly one node named."""
        self.assertEqual(resolver.reading_telling_ref(self.target()),
                         "resolver:" + self.event_ref.split(":")[-1])

    def test_a_reading_with_no_telling_to_reread_still_declares_one(self):
        filed = resolver.file_resolution(self.root, self.target(), self.resolved,
                                         story_path="answers/q3.md", model="m", now=NOW, prior={})
        receipt = json.loads(Path(filed["receipt_path"]).read_text("utf-8"))
        declared = receipt["extractor"]["telling_keys"]
        self.assertEqual(declared, {filed["claim_id"]: resolver.reading_telling_ref(self.target())})
        # And the binder recognizes it as a reading OF THAT NODE.
        claim = {c["claim_id"]: c for c in ts.fold_active_index(self.root)["claims"]}[filed["claim_id"]]
        self.assertEqual(eb.reads_node(declared[filed["claim_id"]], [claim]), self.event_ref)

    def test_a_reading_of_a_known_telling_is_declared_under_that_telling(self):
        target = self.target(telling_ref="classification:answers-q3#aaaaaaaaaaaa")
        filed = resolver.file_resolution(self.root, target, self.resolved,
                                         story_path="answers/q3.md", model="m", now=NOW, prior={})
        receipt = json.loads(Path(filed["receipt_path"]).read_text("utf-8"))
        self.assertEqual(receipt["extractor"]["telling_keys"],
                         {filed["claim_id"]: "classification:answers-q3#aaaaaaaaaaaa"})


class RestatementIsNotAQuestionTests(unittest.TestCase):
    """v333 defect B, the resolver's half: an unplaced moment whose normalized
    label and subject already name a PLACED node is a retelling, not a card."""

    def node(self, node_id: str, label: str, *, placed: bool,
             subjects: Sequence[str] = ("Wren Ashgrove",)) -> dict:
        return {"node_id": node_id, "node_kind": "event", "label": label,
                "event_kind": "moment", "usable_placement": placed,
                "subject_refs": list(subjects), "input_claim_refs": []}

    def test_an_unplaced_restatement_of_a_placed_node_is_found(self):
        projection = {"nodes": [
            self.node("node:" + "1" * 24, "Wren's birth", placed=False),
            self.node("node:" + "2" * 24, "Wren's Birth ", placed=True),
        ]}
        found = resolver.restated_placed_nodes(projection)
        self.assertEqual(found["node:" + "1" * 24]["node_id"], "node:" + "2" * 24)

    def test_a_different_subject_is_a_different_moment(self):
        projection = {"nodes": [
            self.node("node:" + "1" * 24, "Wren's birth", placed=False),
            self.node("node:" + "2" * 24, "Wren's birth", placed=True,
                      subjects=("Juniper Ashgrove",)),
        ]}
        self.assertEqual(resolver.restated_placed_nodes(projection), {})

    def test_two_placed_nodes_under_one_key_are_no_placement_to_inherit(self):
        projection = {"nodes": [
            self.node("node:" + "1" * 24, "Wren's birth", placed=False),
            self.node("node:" + "2" * 24, "Wren's birth", placed=True),
            self.node("node:" + "3" * 24, "Wren's birth", placed=True),
        ]}
        self.assertEqual(resolver.restated_placed_nodes(projection), {})

    def test_a_period_node_is_never_a_restatement(self):
        projection = {"nodes": [
            self.node("node:" + "1" * 24, "Wren's birth", placed=False),
            {**self.node("node:" + "2" * 24, "Wren's birth", placed=True),
             "node_kind": "period"},
        ]}
        self.assertEqual(resolver.restated_placed_nodes(projection), {})

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

    def story(self, stem: str, body: str, moments: list[tuple[str, str, list[str]]],
              *, subject: str = "self", event_kind: str = "moment") -> None:
        """One story file plus one raw handle claim per unplaced moment.

        `subject`/`event_kind` are how the scope tests below get a node that
        is somebody else's: the fold decides the scope from the mention, so
        these tests read the same answer the page does.
        """
        (self.root / "answers" / f"{stem}.md").write_text(
            f"---\ntitle: {stem}\ntype: prompted_answer\n---\n\n{body}\n", "utf-8")
        for label, relation, anchors in moments:
            node_id = tp.derive_node_id(node_kind="event", event_kind=event_kind,
                                        subject_refs=[subject], discriminator=f"{stem}-{label}")
            claim = tc.validate_temporal_claim({
                "source_kind": "import", "claim_type": "relative_order", "subject_mention": subject,
                "event_kind": event_kind, "event_ref": node_id, "event_mention": label,
                "temporal_value": {"relation": relation, "anchors": list(anchors)},
                "evidence": [{"quote": anchors[0]}], "basis": "explicit", "confidence": 0.8,
                "extractor_version": "classifier-claims/rule:5",
                "source_ref": {"source_id": f"classification:answers-{stem}#{label}",
                               "revision": "sha256:" + "1" * 64,
                               "source_path": f"answers/{stem}.md"},
            }, now=NOW)
            ts.write_receipt(self.root, {"source_ref": claim["source_ref"],
                                         "extractor_version": "classifier-claims/rule:5",
                                         "claims": [claim]}, now=NOW)
            self.nodes[label] = node_id
            self.handles[label] = claim["claim_id"]

    def incomplete_story(self, stem: str, body: str, *, title: str) -> str:
        """One story whose classifier event carries an UNFINISHED search.

        The real shape the classifier writes — `classifier_claims.event_claims`
        off an event with `timeline_resolution.status == "incomplete"` — rather
        than a hand-built claim, so the node reaches the fold exactly as the
        owner's vault does.
        """
        import classifier_claims  # noqa: PLC0415 - test-local

        (self.root / "answers" / f"{stem}.md").write_text(
            f"---\ntitle: {stem}\ntype: prompted_answer\n---\n\n{body}\n", "utf-8")
        claim = classifier_claims.event_claims(
            stem=f"answers-{stem}",
            event={"title": title, "description": body, "subject": "self", "date": None,
                   "timeline_resolution": {"status": "incomplete"}},
            revision="sha256:" + "1" * 64,
            source_path=f"answers/{stem}.md",
            now=NOW,
        )[0]
        ts.write_receipt(self.root, {"source_ref": claim["source_ref"],
                                     "extractor_version": claim["extractor_version"],
                                     "claims": [claim]}, now=NOW)
        return str(claim["event_ref"])

    def publish(self):
        import temporal_publication as pub

        return pub.publish(self.root, now=NOW)

    def projection(self) -> dict:
        import temporal_publication as pub

        return pub.read_projection(self.root) or {}

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
        self.assertEqual(sorted(item), ["identity", "include_paths", "key", "node_ids", "prompt", "revisits",
                                        "source_path", "trigger"])
        # v325: a plan for one story that re-opened nothing carries the additive
        # keys empty, so a host that ignores them sees the v316 item.
        self.assertEqual((item["include_paths"], item["revisits"], item["trigger"]), ([], [], False))
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

    def test_a_lived_effect_scene_about_a_relative_is_planned(self):
        """v324: "Grandpa died right around the move" is `other_person` /
        `lived_effect` — the owner's own scene, dated from the owner's own
        spine, so the resolver plans it exactly like his own moments."""
        self.story("a1", "Grandpa died right around the move to Orderville.",
                   [("grandpa", "within", ["the move to Orderville"])],
                   subject="Grandpa")
        self.publish()
        node = next(row for row in self.projection()["nodes"]
                    if row.get("event_kind") == "moment")
        self.assertEqual(node["occurrence_subject_scope"], "other_person")
        self.assertEqual(node["owner_timeline_relation"], "lived_effect")
        self.assertEqual(resolver.plan_items(self.root, limit=5)["pending_events"], 1)

    def test_a_contextual_only_node_is_never_planned(self):
        """A relative's own milestone is not on this vault's axis and nothing
        here dates it. Planning it would date her move from his birthday."""
        self.story("a1", "My grandma moved to Orderville sometime after the war.",
                   [("grandma-move", "after", ["the war"])],
                   subject="my grandma", event_kind="move")
        self.publish()
        node = next(row for row in self.projection()["nodes"]
                    if row.get("event_kind") == "move")
        self.assertEqual(node["owner_timeline_relation"], "contextual_only")
        plan = resolver.plan_items(self.root, limit=5)
        self.assertEqual(plan["pending_events"], 0)
        self.assertEqual(plan["items"], [])

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
        for expected in (1, 2):
            # Each round is a fresh plan, as a host's next hop is. v361
            # (`resolver.A_PLAN_IS_FILED_AGAINST_THE_LEDGER_IT_READ`): replaying
            # round 1's envelope after round 1 wrote the row files nothing.
            item = resolver.plan_items(self.root, limit=5)["items"][0]
            report = resolver.file_envelope(
                self.root, self.envelope(item, self.answer_text("shop"), truncated=True), now=NOW)
            self.assertEqual(report["filed"], 0)
            self.assertEqual(report["outcomes"], {"no_answer_returned": 1})
            entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
            self.assertEqual(entry["status"], "no_answer_returned")
            self.assertEqual(entry["attempts"], expected)
            replay = resolver.file_envelope(
                self.root, self.envelope(item, self.answer_text("shop"), truncated=True), now=NOW)
            self.assertEqual([row["reason"] for row in replay["refused_items"]], ["stale_targets"])
            self.assertEqual(resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]["attempts"], expected)
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
        # A vault no resolver has run on keeps the composer's sentence.
        self.assertIn("shop", str(generic[self.nodes["shop"]]))
        self.assertNotIn("summer", str(generic[self.nodes["shop"]]))
        # v360 (`temporal_publication.NEVER_ASK_WHAT_WAS_NOT_LOOKED_AT`): once
        # the resolver runs here, a date card it has not looked at yet is not
        # drawn at all.
        resolver.save_ledger(self.root, {"version": 1, "nodes": {}})
        pub.publish(self.root, now="2026-09-02T00:00:00Z")
        waiting = {row.get("node_ref") for row in (pub.read_work_items(self.root) or {})["work_items"]}
        self.assertNotIn(self.nodes["shop"], waiting)
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

    def test_an_unfinished_search_gets_a_card_that_asks_the_resolvers_question(self):
        """v333, the owner's dead-end (2026-09-23). A moment whose classifier
        search never finished used to mint NO work item, so the resolver's real
        question never became a card and the page could only show a status the
        person could not act on. It mints its ordinary item now, with the
        resolver's sentence, its window — and the `incomplete` status intact."""
        import temporal_publication as pub

        node_id = self.incomplete_story(
            "c5", "Grandma stepped in during bullying.",
            title="Grandma stepped in during bullying",
        )
        self.publish()
        nodes = {node["node_id"]: node for node in (pub.read_projection(self.root) or {})["nodes"]}
        self.assertEqual(nodes[node_id]["timeline_resolution_status"], "incomplete")
        self.assertFalse(nodes[node_id].get("usable_placement"))
        question = ("Roughly how old were you when Grandma stepped in for you like that "
                    "— still in elementary school, or later?")
        resolver.save_ledger(self.root, {"version": 1, "nodes": {node_id: {
            "label": "Grandma stepped in during bullying", "source_path": "answers/c5.md",
            "status": "unknown", "question": question, "at": NOW,
            # Four years: a window a card may still ask about. One wider than
            # about five years is asked only when hot (v360 follow-up,
            # `temporal_publication.A_WIDE_ESTIMATE_IS_ASKED_ONLY_WHEN_HOT`).
            "estimate": {"earliest": "1987", "latest": "1990", "confidence": 0.4,
                         "basis": [{"kind": "residence", "text": "the Cedarport years"}]}}}})
        pub.publish(self.root, now="2026-09-23T12:00:00Z")
        rows = {row.get("node_ref"): row
                for row in (pub.read_work_items(self.root) or {})["work_items"]}
        self.assertIn(node_id, rows)
        mine = rows[node_id]
        self.assertEqual(mine["prompt_intent"], question)
        self.assertEqual(mine["question_source"], "resolver")
        self.assertEqual(mine["probable_window"]["earliest"], "1987")
        self.assertEqual(mine["probable_window"]["latest"], "1990")
        # The honest status is kept, not traded for the question.
        published = {node["node_id"]: node
                     for node in (pub.read_projection(self.root) or {})["nodes"]}
        self.assertEqual(published[node_id]["timeline_resolution_status"], "incomplete")

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


class NotAnEventTests(LegsTests):
    """ADR 0037's amendment — the resolver retires what was never an event.

    lifehug#365 item 5: the classifier read an anticipated milestone, a
    correction about the data itself and a bare statement of a name as
    occurrences, and each became an undated moment the loop could only ask
    about forever. The verdict is a DURABLE CORRECTION through the ordinary
    path — the claims stay on disk, retracted and dated — and the node leaves
    the projection on the republish that already follows filing.
    """

    def verdict_text(self, label: str, *, kind: str = "future",
                     reason: str = "The shop has not opened yet.",
                     answer: object = None) -> str:
        return json.dumps({"answers": [{
            "node_id": self.nodes[label], "answer": answer, "basis": "inferred",
            "confidence": 0.2, "citations": [], "fact_key": "not_an_event",
            "reason": reason, "question": None, "also_resolves": [],
            "not_an_event": {"kind": kind, "reason": reason},
        }]})

    def planned(self, body: str, label: str = "shop") -> dict:
        self.story("a1", body, [(label, "after", ["the move to Cedarport"])])
        self.publish()
        return resolver.plan_items(self.root, limit=5)["items"][0]

    # -- verification -----------------------------------------------------

    def test_every_kind_in_the_closed_set_is_accepted(self):
        for kind in resolver.NOT_AN_EVENT_KINDS:
            with self.subTest(kind=kind):
                verdict, why = resolver.verify_not_an_event(
                    {"answer": None, "not_an_event": {"kind": kind, "reason": "because"}})
                self.assertEqual(why, "ok")
                self.assertEqual(verdict, {"kind": kind, "reason": "because"})

    def test_a_kind_outside_the_set_is_refused(self):
        self.assertEqual(
            resolver.verify_not_an_event(
                {"answer": None, "not_an_event": {"kind": "boring", "reason": "r"}}),
            (None, "verdict_kind_unknown"))

    def test_a_verdict_beside_a_date_is_refused(self):
        self.assertEqual(
            resolver.verify_not_an_event(
                {"answer": {"earliest": "1996", "latest": "1996"},
                 "not_an_event": {"kind": "future", "reason": "r"}}),
            (None, "verdict_with_an_answer"))

    def test_an_ordinary_answer_carries_no_verdict(self):
        self.assertEqual(resolver.verify_not_an_event({"answer": None})[1], "no_verdict")

    # -- filing -----------------------------------------------------------

    def test_a_verdict_retracts_the_claims_and_the_node_leaves_the_page(self):
        import temporal_publication as pub

        item = self.planned("One day the shop will open, after the move to Cedarport.")
        before = {row["node_id"] for row in (pub.read_projection(self.root) or {}).get("nodes") or ()}
        self.assertIn(self.nodes["shop"], before)

        report = resolver.file_envelope(
            self.root, self.envelope(item, self.verdict_text("shop")), now=NOW)

        self.assertEqual(report["filed"], 0)
        self.assertEqual(report["retracted"], 1)
        self.assertEqual(report["outcomes"], {resolver.NOT_AN_EVENT_STATUS: 1})
        self.assertEqual(report["refused_items"], [])
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.root)["claims"]}
        self.assertEqual(by_id[self.handles["shop"]]["status"], "retracted")
        after = {row["node_id"] for row in (pub.read_projection(self.root) or {}).get("nodes") or ()}
        self.assertNotIn(self.nodes["shop"], after)

    def test_the_ledger_records_the_status_the_kind_and_the_reason(self):
        item = self.planned("One day the shop will open, after the move to Cedarport.")
        resolver.file_envelope(
            self.root,
            self.envelope(item, self.verdict_text("shop", kind="meta",
                                                  reason="This turn corrects the last one.")),
            now=NOW)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], resolver.NOT_AN_EVENT_STATUS)
        self.assertEqual(entry["kind"], "meta")
        self.assertEqual(entry["reason"], "This turn corrects the last one.")
        self.assertEqual(entry["retracted"], [self.handles["shop"]])

    def test_the_retraction_is_a_correction_and_never_a_delete(self):
        item = self.planned("One day the shop will open, after the move to Cedarport.")
        resolver.file_envelope(self.root, self.envelope(item, self.verdict_text("shop")), now=NOW)
        mine = [row for row in ts.load_temporal_corrections(self.root)
                if row.scope == resolver.NOT_AN_EVENT_SCOPE]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].kind, "retract")
        self.assertEqual(list(mine[0].claim_ids), [self.handles["shop"]])
        self.assertIn("future", mine[0].reason)
        # The claim is still on disk, retracted — never deleted.
        self.assertTrue((self.root / mine[0].relative_path).is_file())

    def test_a_verdict_with_a_date_beside_it_files_the_date_instead(self):
        """Verification is total: a contradiction is not a verdict."""
        item = self.planned("We moved to Cedarport in June 1996; the shop opened that month.")
        report = resolver.file_envelope(
            self.root,
            self.envelope(item, json.dumps({"answers": [{
                "node_id": self.nodes["shop"],
                "answer": {"earliest": "1996-06", "latest": "1996-06"},
                "basis": "stated", "confidence": 0.9, "fact_key": "shop_opening",
                "citations": [{"doc": "story", "quote": "the shop opened that month"}],
                "reason": "The story says so.", "question": None, "also_resolves": [],
                "not_an_event": {"kind": "future", "reason": "r"}}]})),
            now=NOW)
        self.assertEqual(report["filed"], 1)
        self.assertEqual(report["retracted"], 0)
        self.assertEqual(report["outcomes"], {"resolved": 1})

    # -- once retired, never re-asked -------------------------------------

    def test_a_retired_moment_is_never_planned_again(self):
        item = self.planned("One day the shop will open, after the move to Cedarport.")
        resolver.file_envelope(self.root, self.envelope(item, self.verdict_text("shop")), now=NOW)
        plan = resolver.plan_items(self.root, limit=5)
        self.assertEqual(plan["items"], [])
        self.assertEqual(plan["pending_events"], 0)
        self.assertTrue(plan["complete"])

    def test_refile_skips_a_retired_moment(self):
        item = self.planned("One day the shop will open, after the move to Cedarport.")
        resolver.file_envelope(self.root, self.envelope(item, self.verdict_text("shop")), now=NOW)
        report = resolver.refile_from_ledger(self.root, now=NOW)
        self.assertEqual(report.get("refiled", 0), 0)
        self.assertEqual(report["skipped"], 1)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], resolver.NOT_AN_EVENT_STATUS)

    def test_a_retired_moment_is_not_an_open_question(self):
        item = self.planned("One day the shop will open, after the move to Cedarport.")
        report = resolver.file_envelope(
            self.root, self.envelope(item, self.verdict_text("shop")), now=NOW)
        self.assertEqual(report["open_questions"], [])

    # -- the prompt says so -----------------------------------------------

    def test_the_prompt_offers_the_verdict_and_names_every_kind(self):
        self.assertIn("not_an_event", resolver.PROMPT)
        for kind in resolver.NOT_AN_EVENT_KINDS:
            self.assertIn(f'"{kind}"', resolver.PROMPT)


if __name__ == "__main__":
    unittest.main()


class RevisitTests(LegsTests):
    """v325: a new story re-opens the settled unknowns it bears on, an answer
    names the moment it was given for, a handle binds to a node, and an
    unknown keeps an estimate the page can draw.

    Before v325 an ``unknown`` was terminal and the resolver planned only the
    story just filed, so a fact answering an OLD question helped only if it
    happened to become a new dated event under the same words (the founder's
    grandfathers' deaths, 2026-09-21: the dates arrived, the question stayed).
    """

    def settle_unknown(self, label: str, question: str, source_path: str = "answers/a1.md") -> None:
        ledger = resolver.load_ledger(self.root)
        ledger.setdefault("nodes", {})[self.nodes[label]] = {
            "label": label, "source_path": source_path, "status": "unknown",
            "question": question, "at": NOW}
        resolver.save_ledger(self.root, ledger)

    def two_stories(self) -> None:
        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.story("a2", "We moved to Cedarport in June 1996; the shop opened that same summer.",
                   [("wedding", "after", ["the shop opening"])])
        self.publish()
        self.settle_unknown("shop", "Which year did the shop open?")

    def answer(self, node_id: str, **fields) -> dict:
        row = {"node_id": node_id, "answer": None, "basis": "stated", "confidence": 0.9,
               "fact_key": "shop_opening", "citations": [], "reason": "The story says so.",
               "question": None, "also_resolves": []}
        row.update(fields)
        return row

    def item_for(self, plan: dict, source_path: str) -> dict:
        return next(item for item in plan["items"] if item["source_path"] == source_path)

    # -- revisits -----------------------------------------------------------

    def test_a_settled_unknown_stays_settled_until_a_story_bears_on_it(self):
        self.two_stories()
        plan = resolver.plan_items(self.root, limit=5)
        self.assertEqual([item["source_path"] for item in plan["items"]], ["answers/a2.md"])
        self.assertEqual(plan["pending_events"], 1)

    def test_a_new_story_reopens_the_unknown_its_words_reach(self):
        self.two_stories()
        read = resolver._Read(self.root, triggers={"answers/a2.md"})
        self.assertEqual(read.revisit, {self.nodes["shop"]: {"trigger": "answers/a2.md", "why": "retrieval"}})
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a2.md"}, restrict=True, read=read)
        # The story just told first, then the story it re-opened.
        self.assertEqual([item["source_path"] for item in plan["items"]], ["answers/a2.md", "answers/a1.md"])
        self.assertEqual(plan["pending_events"], 2)
        told = self.item_for(plan, "answers/a2.md")
        reopened = self.item_for(plan, "answers/a1.md")
        self.assertTrue(told["trigger"])
        self.assertEqual(told["include_paths"], [])
        # The new story's own prompt lists the question it may bear on…
        self.assertIn(self.nodes["shop"], told["prompt"])
        self.assertIn("Which year did the shop open?", told["prompt"])
        # …and the re-opened moment's prompt carries the new story's passage.
        self.assertFalse(reopened["trigger"])
        self.assertEqual(reopened["include_paths"], ["answers/a2.md"])
        self.assertEqual(reopened["revisits"], [self.nodes["shop"]])
        self.assertIn("[answers/a2.md#p0]", reopened["prompt"])
        self.assertIn("moved to Cedarport in June 1996", reopened["prompt"])

    def test_a_revisited_unknown_files_its_answer_from_the_new_passage(self):
        self.two_stories()
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a2.md"}, restrict=True)
        reopened = self.item_for(plan, "answers/a1.md")
        text = json.dumps({"answers": [self.answer(
            self.nodes["shop"], answer={"earliest": "1996-06", "latest": "1996-08"}, basis="inferred",
            citations=[{"doc": "answers/a2.md#p0", "quote": "moved to Cedarport in June 1996"}])]})
        # Leg C the hosted way: no --source, the envelope alone says what was planned.
        report = resolver.file_envelope(self.root, self.envelope(reopened, text, include_paths=reopened["include_paths"],
                                                                 trigger=False), now=NOW)
        self.assertEqual(report["filed"], 1)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], "resolved")
        self.assertEqual(entry["revisited_by"], ["answers/a2.md"])
        self.assertEqual(entry["revisit_why"], "retrieval")

    def test_a_story_reopens_an_unknown_once(self):
        self.two_stories()
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a2.md"}, restrict=True)
        reopened = self.item_for(plan, "answers/a1.md")
        text = json.dumps({"answers": [self.answer(self.nodes["shop"], question="Which year did the shop open?")]})
        resolver.file_envelope(self.root, self.envelope(reopened, text, include_paths=reopened["include_paths"]), now=NOW)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual((entry["status"], entry["revisited_by"]), ("unknown", ["answers/a2.md"]))
        self.assertEqual(resolver._Read(self.root, triggers={"answers/a2.md"}).revisit, {})
        # A DIFFERENT story bearing on it re-opens it again.
        self.story("a3", "The shop on Cedarport's main street opened the year after the move.", [])
        self.publish()
        self.assertIn(self.nodes["shop"], resolver._Read(self.root, triggers={"answers/a3.md"}).revisit)

    def test_the_conversation_names_the_moment_it_answers_whatever_the_words(self):
        import temporal_publication as pub

        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        # The card exists once the resolver has looked and asked (v360,
        # `temporal_publication.NEVER_ASK_WHAT_WAS_NOT_LOOKED_AT`).
        self.settle_unknown("shop", "Which year did the shop open?")
        self.publish()
        rows = (pub.read_work_items(self.root) or {})["work_items"]
        work_item_id = next(row["work_item_id"] for row in rows if row.get("node_ref") == self.nodes["shop"])
        (self.root / "answers" / "a2.md").write_text(
            "---\ntitle: a2\ntype: conversation_message\n"
            f'session_ref: "conversation:cand:work_item:{work_item_id}"\n---\n\n'
            "Honestly I could not say. Ask my sister.\n", "utf-8")
        self.publish()
        self.settle_unknown("shop", "Which year did the shop open?")
        read = resolver._Read(self.root, triggers={"answers/a2.md"})
        self.assertEqual(read.revisit, {self.nodes["shop"]: {"trigger": "answers/a2.md", "why": "conversation"}})
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a2.md"}, restrict=True, read=read)
        self.assertEqual([item["source_path"] for item in plan["items"]], ["answers/a1.md"])
        self.assertIn("Ask my sister", self.item_for(plan, "answers/a1.md")["prompt"])

    def test_the_conversation_for_an_anchor_handle_reopens_the_moments_that_hang_on_it(self):
        import temporal_publication as pub
        import temporal_work_items as twi

        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        self.settle_unknown("shop", "Which year did the shop open?")
        self.publish()
        rows = (pub.read_work_items(self.root) or {})["work_items"]
        handle_ref = twi.anchor_handle_ref("the move to Cedarport")
        anchor_items = [row for row in rows if row.get("subject_ref") == handle_ref]
        self.assertEqual(len(anchor_items), 1, [row.get("subject_ref") for row in rows])
        (self.root / "answers" / "a2.md").write_text(
            "---\ntitle: a2\ntype: conversation_message\n"
            f'session_ref: "conversation:cand:work_item:{anchor_items[0]["work_item_id"]}"\n---\n\n'
            "That was my grandparents' move, not mine.\n", "utf-8")
        self.publish()
        self.settle_unknown("shop", "Which year did the shop open?")
        read = resolver._Read(self.root, triggers={"answers/a2.md"})
        self.assertEqual(read.revisit, {self.nodes["shop"]: {"trigger": "answers/a2.md", "why": "conversation"}})

    # -- estimates ----------------------------------------------------------

    def test_an_estimate_is_verified_mechanically_and_never_before_the_birth(self):
        sp = spine()
        ok, why = resolver.verify_estimate({"estimate": {
            "earliest": "1996", "latest": "1998", "confidence": 0.5,
            "basis": [{"kind": "residence", "text": "the Cedarport years"},
                      {"kind": "vibes", "text": "it feels like the nineties", "ref": "landmark:residences:3"}]}}, sp=sp)
        self.assertEqual(why, "ok")
        self.assertEqual(ok, {"earliest": "1996", "latest": "1998", "confidence": 0.5,
                              "basis": [{"kind": "residence", "text": "the Cedarport years"},
                                        {"kind": "other", "text": "it feels like the nineties",
                                         "ref": "landmark:residences:3"}]})
        self.assertEqual(resolver.verify_estimate({}, sp=sp), (None, "no_estimate"))
        self.assertEqual(resolver.verify_estimate({"estimate": {"earliest": "1960", "latest": "1970",
                                                                 "basis": [{"kind": "story", "text": "x"}]}}, sp=sp),
                         (None, "pre_birth"))
        self.assertEqual(resolver.verify_estimate({"estimate": {"earliest": "1999", "latest": "1996",
                                                                 "basis": [{"kind": "story", "text": "x"}]}}, sp=sp),
                         (None, "estimate_reversed"))
        # A single year is a one-year window, never an open end: an estimate is bounded.
        self.assertEqual(resolver.verify_estimate({"estimate": {"earliest": "1996", "latest": None,
                                                                 "basis": [{"kind": "story", "text": "x"}]}}, sp=sp)[0],
                         {"earliest": "1996", "latest": "1996", "confidence": 0.4,
                          "basis": [{"kind": "story", "text": "x"}]})
        self.assertEqual(resolver.verify_estimate({"estimate": {"earliest": "1996", "latest": "1998"}}, sp=sp),
                         (None, "estimate_without_basis"))

    def test_an_estimate_before_the_owners_birth_stands_when_the_moment_is_somebody_elses(self):
        # v330. The father's mission fell before the owner was born; that is
        # not "family history, not a guess about this life" — it is the guess.
        sp = spine()
        estimate = {"estimate": {"earliest": "1973", "latest": "1975", "confidence": 0.5,
                                 "basis": [{"kind": "story", "text": "born 4 June 1954; served at 19-21"}]}}
        self.assertEqual(resolver.verify_estimate(estimate, sp=sp, subject="James Edwin Taylor")[1], "ok")
        self.assertEqual(resolver.verify_estimate(estimate, sp=sp, subject="self"), (None, "pre_birth"))
        self.assertEqual(resolver.verify_estimate(estimate, sp=sp, subject=sp["owner_name"]), (None, "pre_birth"))
        self.assertEqual(resolver.verify_estimate(estimate, sp=sp), (None, "pre_birth"))

    def test_a_conversation_trigger_carries_the_cards_earlier_messages(self):
        import temporal_publication as pub

        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        # The card exists once the resolver has looked and asked (v360,
        # `temporal_publication.NEVER_ASK_WHAT_WAS_NOT_LOOKED_AT`).
        self.settle_unknown("shop", "Which year did the shop open?")
        self.publish()
        rows = (pub.read_work_items(self.root) or {})["work_items"]
        work_item_id = next(row["work_item_id"] for row in rows if row.get("node_ref") == self.nodes["shop"])
        session = f'session_ref: "conversation:cand:work_item:{work_item_id}"\n'
        (self.root / "answers" / "a2.md").write_text(
            "---\ntitle: a2\ntype: conversation_message\n" + session + "---\n\nIt was the summer I turned nine.\n", "utf-8")
        (self.root / "answers" / "a3.md").write_text(
            "---\ntitle: a3\ntype: conversation_message\n" + session + "---\n\nNo wait, I was born in 1987.\n", "utf-8")
        (self.root / "answers" / "a4.md").write_text(
            "---\ntitle: a4\ntype: conversation_message\n"
            'session_ref: "conversation:cand:work_item:work:000000000000000000000000"\n---\n\nUnrelated card.\n', "utf-8")
        self.publish()
        self.settle_unknown("shop", "Which year did the shop open?")
        read = resolver._Read(self.root, triggers={"answers/a3.md"})
        self.assertEqual(read.session_siblings("answers/a3.md"), ["answers/a2.md"])
        self.assertEqual(read.session_siblings("answers/a1.md"), [])
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a3.md"}, restrict=True, read=read)
        item = self.item_for(plan, "answers/a1.md")
        self.assertEqual(item["include_paths"], ["answers/a2.md", "answers/a3.md"])
        self.assertIn("the summer I turned nine", item["prompt"])
        self.assertIn("born in 1987", item["prompt"])
        self.assertNotIn("Unrelated card", item["prompt"])

    def test_an_unknown_keeps_its_estimate_and_the_page_floats_the_dot_over_it(self):
        import temporal_publication as pub

        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        before = (pub.read_projection(self.root) or {})["calculation_rule_version"]
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        # v360 (`resolver.AN_ESTIMATE_PLACES_AS_THE_SYSTEMS_INFERENCE`): a
        # GROUNDED estimate (a residence, a tenure, ...) now places its moment;
        # this is the window an ungrounded one — the resolver's own reading of
        # the story — still floats as sky. Placement is pinned in
        # tests/test_v360_look_before_asking.py.
        text = json.dumps({"answers": [self.answer(
            self.nodes["shop"], question="Which year did the shop open?",
            estimate={"earliest": "1996", "latest": "1998", "confidence": 0.5,
                      "basis": [{"kind": "story", "text": "the Cedarport years"}]})]})
        report = resolver.file_envelope(self.root, self.envelope(item, text), now=NOW)
        self.assertEqual((report["filed"], report["estimates"], report["outcomes"]), (0, 1, {"unknown": 1}))
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["estimate"], {"earliest": "1996", "latest": "1998", "confidence": 0.5,
                                             "basis": [{"kind": "story", "text": "the Cedarport years"}]})
        window = {"earliest": "1996", "latest": "1998", "confidence": 0.5, "source": "resolver",
                  "basis": [{"kind": "story", "text": "the Cedarport years"}]}
        rows = {row.get("node_ref"): row for row in (pub.read_work_items(self.root) or {})["work_items"]}
        self.assertEqual(rows[self.nodes["shop"]]["probable_window"], window)
        nodes = {node["node_id"]: node for node in (pub.read_projection(self.root) or {})["nodes"]}
        self.assertEqual(nodes[self.nodes["shop"]]["probable_window"], window)
        # An estimate is a display decision, never arithmetic: the rule version
        # holds, nothing is placed, and every other node carries no window.
        self.assertEqual((pub.read_projection(self.root) or {})["calculation_rule_version"], before)
        self.assertFalse(nodes[self.nodes["shop"]].get("usable_placement"))
        self.assertTrue(all("probable_window" not in node for nid, node in nodes.items() if nid != self.nodes["shop"]))

    # -- handle binds -------------------------------------------------------

    def test_a_handle_bind_files_an_ordering_claim_on_the_node_and_retires_the_raw_handle(self):
        import temporal_publication as pub
        import temporal_work_items as twi

        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.story("b1", "We moved house the year I finished school.",
                   [("move", "after", ["finishing school"])])
        self.publish()
        self.settle_unknown("shop", "Which year did the shop open?")
        self.publish()
        # v361 (`resolver.A_PLAN_IS_FILED_AGAINST_THE_LEDGER_IT_READ`): planned from
        # the ledger it is filed against.
        item = self.item_for(resolver.plan_items(self.root, limit=5, force=True), "answers/a1.md")
        handle_ref = twi.anchor_handle_ref("the move to Cedarport")
        rows = (pub.read_work_items(self.root) or {})["work_items"]
        self.assertTrue(any(row.get("subject_ref") == handle_ref for row in rows))
        text = json.dumps({"answers": [self.answer(
            self.nodes["shop"], question="Which year did the shop open?",
            estimate={"earliest": "1996", "latest": "1998", "confidence": 0.4,
                      "basis": [{"kind": "related_moment", "text": "after the move"}]},
            handle_binds=[{"handle": "the move to Cedarport", "node_id": self.nodes["move"]},
                          {"handle": "the move to Cedarport", "node_id": "node:nobody"},
                          {"handle": "something else entirely", "node_id": self.nodes["move"]}])]})
        report = resolver.file_envelope(self.root, self.envelope(item, text), now=NOW)
        self.assertEqual((report["filed"], report["bound"]), (0, 1))
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], "unknown")
        [bind] = entry["handle_binds"]
        self.assertEqual((bind["handle"], bind["node_id"], bind["superseded"]),
                         ("the move to Cedarport", self.nodes["move"], [self.handles["shop"]]))
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.root)["claims"]}
        self.assertEqual(by_id[self.handles["shop"]]["status"], "superseded")
        mine = by_id[bind["claim_id"]]
        self.assertEqual(mine["claim_type"], "relative_order")
        self.assertEqual(mine["temporal_value"], {"relation": "after", "anchors": [self.nodes["move"]]})
        self.assertEqual(mine["extractor_version"], resolver.EXTRACTOR_VERSION)
        # The republish that follows: the handle names something now, so the
        # `anchor:` work item that asked whose move it was is gone.
        rows = (pub.read_work_items(self.root) or {})["work_items"]
        self.assertFalse(any(row.get("subject_ref") == handle_ref for row in rows),
                         [row.get("subject_ref") for row in rows])


class RefineAndBackfillTests(LegsTests):
    """v325: a wide resolver-dated reading is re-asked when an exact date arrives,
    never downgraded; and `--estimate-missing` asks a settled unknown for the
    estimate it lacks, once."""

    def file_wide(self) -> dict:
        self.story("a1", "The shop opened sometime in the late nineties, after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        item = resolver.plan_items(self.root, limit=5)["items"][0]
        text = json.dumps({"answers": [{
            "node_id": self.nodes["shop"], "answer": {"earliest": "1996", "latest": "1999"}, "basis": "stated",
            "confidence": 0.6, "fact_key": "shop_opening", "reason": "late nineties",
            "citations": [{"doc": "story", "quote": "sometime in the late nineties"}], "question": None,
            "also_resolves": []}]})
        report = resolver.file_envelope(self.root, self.envelope(item, text), now=NOW)
        self.assertEqual(report["filed"], 1)
        return item

    def test_a_wide_resolver_reading_is_reopened_by_a_story_with_the_exact_date(self):
        import temporal_publication as pub

        self.file_wide()
        nodes = {n["node_id"]: n for n in (pub.read_projection(self.root) or {})["nodes"]}
        self.assertTrue(nodes[self.nodes["shop"]]["usable_placement"])
        # A placed moment is not a target… unless the resolver dated it wide.
        self.story("a2", "The shop on Cedarport's main street opened on 12 June 1997, I have the photo.", [])
        self.publish()
        read = resolver._Read(self.root, triggers={"answers/a2.md"})
        self.assertEqual(read.revisit, {self.nodes["shop"]: {"trigger": "answers/a2.md", "why": "refine"}})
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a2.md"}, restrict=True, read=read)
        item = next(i for i in plan["items"] if i["source_path"] == "answers/a1.md")
        self.assertIn("12 June 1997", item["prompt"])
        # Sharper, verified against the new passage → replaces the wide reading.
        text = json.dumps({"answers": [{
            "node_id": self.nodes["shop"], "answer": {"earliest": "1997-06-12", "latest": "1997-06-12"},
            "basis": "stated", "confidence": 0.9, "fact_key": "shop_opening", "reason": "the photo",
            "citations": [{"doc": "answers/a2.md#p0", "quote": "opened on 12 June 1997"}],
            "question": None, "also_resolves": []}]})
        report = resolver.file_envelope(self.root, self.envelope(item, text, include_paths=item["include_paths"]), now=NOW)
        self.assertEqual(report["filed"], 1)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual((entry["status"], entry["answer"]["best"], entry["refined_from"]["best"], entry["revisit_why"]),
                         ("resolved", "1997-06-12", "1996/1999", "refine"))
        nodes = {n["node_id"]: n for n in (pub.read_projection(self.root) or {})["nodes"]}
        self.assertEqual(nodes[self.nodes["shop"]]["best_temporal_value"]["best"], "1997-06-12")

    def test_a_story_with_no_date_in_it_refines_nothing(self):
        self.file_wide()
        self.story("a2", "I think the shop in Cedarport did well; the move was hard on everyone.", [])
        self.publish()
        # Same words, no year anywhere: a refine would only buy the same answer.
        self.assertEqual(resolver._Read(self.root, triggers={"answers/a2.md"}).revisit, {})

    def test_a_refine_that_finds_nothing_sharper_keeps_the_standing_answer(self):
        self.file_wide()
        self.story("a2", "I think the shop in Cedarport did well by 1998; the move was hard on everyone.", [])
        self.publish()
        read = resolver._Read(self.root, triggers={"answers/a2.md"})
        self.assertIn(self.nodes["shop"], read.revisit)
        plan = resolver.plan_items(self.root, limit=5, only_sources={"answers/a2.md"}, restrict=True, read=read)
        item = next(i for i in plan["items"] if i["source_path"] == "answers/a1.md")
        text = json.dumps({"answers": [{"node_id": self.nodes["shop"], "answer": None, "basis": "inferred",
                                        "confidence": 0.2, "fact_key": "shop_opening", "reason": "nothing new",
                                        "citations": [], "question": "When exactly?", "also_resolves": []}]})
        report = resolver.file_envelope(self.root, self.envelope(item, text, include_paths=item["include_paths"]), now=NOW)
        self.assertEqual(report["outcomes"], {"kept_resolved": 1})
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual((entry["status"], entry["answer"]["best"], entry["refine_attempted_by"]),
                         ("resolved", "1996/1999", ["answers/a2.md"]))
        # Once per story here too.
        self.assertEqual(resolver._Read(self.root, triggers={"answers/a2.md"}).revisit, {})

    def test_estimate_missing_asks_a_settled_unknown_once_for_its_window(self):
        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        resolver.save_ledger(self.root, {"version": 1, "nodes": {self.nodes["shop"]: {
            "label": "shop", "source_path": "answers/a1.md", "status": "unknown",
            "question": "Which year did the shop open?", "at": NOW}}})
        self.assertEqual(resolver.plan_items(self.root, limit=5)["items"], [])
        plan = resolver.plan_items(self.root, limit=5, estimate_missing=True)
        self.assertEqual([i["node_ids"] for i in plan["items"]], [[self.nodes["shop"]]])
        text = json.dumps({"answers": [{"node_id": self.nodes["shop"], "answer": None, "basis": "inferred",
                                        "confidence": 0.3, "fact_key": "shop_opening", "reason": "the move bounds it",
                                        "citations": [], "question": "Which year did the shop open?", "also_resolves": [],
                                        "estimate": {"earliest": "1996", "latest": "1999", "confidence": 0.3,
                                                     "basis": [{"kind": "related_moment", "text": "after the move"}]}}]})
        report = resolver.file_envelope(self.root, self.envelope(plan["items"][0], text), now=NOW)
        self.assertEqual((report["estimates"], report["outcomes"]), (1, {"unknown": 1}))
        # With its estimate in hand it is settled again, even for a backfill run.
        self.assertEqual(resolver.plan_items(self.root, limit=5, estimate_missing=True)["items"], [])


class OwnerAliasAndFallbackTests(unittest.TestCase):
    """v325: the owner's nickname is the owner; an unverified proposal still floats the dot."""

    def test_the_owners_nickname_passes_the_age_refusal(self):
        sp = spine(owner_name="David James Taylor", owner_names=["dave", "david", "david james taylor"])
        self.assertTrue(resolver._subject_is_owner("Dave", sp))
        self.assertTrue(resolver._subject_is_owner("David James Taylor", sp))
        self.assertFalse(resolver._subject_is_owner("Mom", sp))
        # Without the spelling list the old rule still holds: the full name and its first word.
        plain = spine(owner_name="David James Taylor")
        self.assertTrue(resolver._subject_is_owner("David", plain))
        self.assertFalse(resolver._subject_is_owner("Dave", plain))

    def test_a_refused_proposal_becomes_the_estimate(self):
        sp = spine()
        item = {"answer": {"earliest": "1999-07", "latest": "2000-07"}, "reason": "age 18 off the birthday"}
        estimate, why = resolver.verify_estimate(
            {"estimate": {**item["answer"], "confidence": 0.3,
                          "basis": [{"kind": "story", "text": item["reason"]}]}}, sp=sp)
        self.assertEqual(why, "ok")
        self.assertEqual(estimate, {"earliest": "1999-07", "latest": "2000-07", "confidence": 0.3,
                                    "basis": [{"kind": "story", "text": "age 18 off the birthday"}]})


class ProposalAdoptionTests(LegsTests):
    """v325: `--estimate-missing` first adopts every refused proposal as an estimate, free."""

    def test_a_refused_proposal_is_adopted_as_the_estimate_without_a_model_call(self):
        import temporal_publication as pub

        self.story("a1", "The shop opened at some point after we moved.",
                   [("shop", "after", ["the move to Cedarport"])])
        self.publish()
        resolver.save_ledger(self.root, {"version": 1, "nodes": {self.nodes["shop"]: {
            "label": "shop", "source_path": "answers/a1.md", "status": "unverified", "why": "citations_unverified",
            "proposed": {"earliest": "1996", "latest": "1998"}, "reason": "the move bounds it", "at": NOW}}})
        report = resolver.resolve_vault(self.root, model="test-model", execute=False, limit=5, concurrency=1,
                                        only_sources=None, force=False, now=NOW, estimate_missing=True)
        self.assertEqual(report["estimates_adopted"], 1)
        entry = resolver.load_ledger(self.root)["nodes"][self.nodes["shop"]]
        self.assertEqual(entry["status"], "unverified")
        self.assertEqual(entry["estimate"], {"earliest": "1996", "latest": "1998", "confidence": 0.3,
                                             "basis": [{"kind": "story", "text": "the move bounds it"}]})
        # An `unverified` row asked no question, so no card is drawn for it
        # (v360, `temporal_publication.NEVER_ASK_WHAT_WAS_NOT_LOOKED_AT`);
        # the window floats on the node itself.
        nodes = {node["node_id"]: node for node in (pub.read_projection(self.root) or {})["nodes"]}
        self.assertEqual(nodes[self.nodes["shop"]]["probable_window"]["earliest"], "1996")
        # With its estimate adopted, the backfill has nothing left to ask.
        self.assertEqual(resolver.plan_items(self.root, limit=5, estimate_missing=True)["items"], [])
