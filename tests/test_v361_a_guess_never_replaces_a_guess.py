"""v361 (the A14bc churn, 2026-09-26) — a guess never replaces a guess.

On the owner's hosted vault `answers/A14bc.md` — an immutable, dateless answer
about four children's activities — was re-resolved six times in one morning.
Its two dateless moments ("Harvey's swimming classes", "Going to James's
baseball games") cycled `no_answer_returned` -> `unknown` + a new
`placed_by_estimate` with a different month guess each time (2018-01 ->
2018-05 -> 2019-05), and every different guess retired the standing estimate
by a correction and filed a new claim and a full republish. The trigger was
the archive-classification backfill: every "Classify archive chunk" commit
starts its own placement chain, and each chain's leg A planned the SAME
vault-wide item from the SAME ledger, then filed it minutes later against a
ledger another chain had already written.

Four named rules, each guarded here on a synthetic vault with the real shapes
(the real minter, the real fold, the real legs A and C):

* `resolver.A_PLAN_IS_FILED_AGAINST_THE_LEDGER_IT_READ` — the plan identity
  carries each moment's ledger row, so the second and third envelope of one
  selection are `stale_targets` and file nothing;
* `resolver.AN_ESTIMATE_IS_REVISITED_ONLY_BY_A_DATED_STORY` — a moment placed
  by the system's own estimate is not planned again by the vault-wide ordering,
  and only a story that carries a date (or his answer to its card) re-opens it;
* `resolver.A_GUESS_NEVER_REPLACES_A_GUESS` — a different month from the same
  undated evidence files nothing; a materially narrower window inside the
  standing one, or one read from a dated story, replaces it;
* `resolver.A_SILENCE_NEVER_UNSETTLES_A_READING` — a silent envelope leaves a
  settled row exactly as it stood.

And the owner's answer to the Charlee card (*"Charlee switched from football to
track her freshmen year January 2026"*) places the moment from his own words
(`answer_placement.A_DATE_HE_SAID_IN_A_SENTENCE_IS_A_DATE_HE_SAID`, under
`temporal_timeline.AN_ANSWER_IS_THE_PLACEMENT`), over the resolver's estimate.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import resolver  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
from test_v360_look_before_asking import NOW, Vault, envelope, unknown  # noqa: E402

A14BC = ("What I try to do for my kids: Harvey's swimming classes, going to James's "
         "baseball games, Charlee's track meets and Dottie's dance recitals. I show up "
         "and I pay attention.")
C20 = ("James Everett moved between baseball teams a lot, and Charlee moved from football "
       "to track.")
#: An archive chunk the backfill classifies: shares the moments' words, names no date.
CHUNK = ("Harvey loved the swimming pool and his swimming classes. We went to James's "
         "baseball games most weekends, and Charlee ran at track.")
LITTLE_LEAGUE = ("James started Little League baseball in April 2019, and I went to every one of "
                 "James's baseball games that spring.")
CHARLEE_ANSWER = "Charlee switched from football to track her freshmen year January 2026"


def estimate(earliest: str, latest: str, kind: str = "life_stage", confidence: float = 0.35) -> dict:
    return {"earliest": earliest, "latest": latest, "confidence": confidence,
            "basis": [{"kind": kind, "text": "youth baseball typically begins around age 5-6"}]}


def silent(item: dict) -> dict:
    """An envelope whose purchase came back with nothing (truncated)."""
    row = envelope(item, [])
    row["items"][0].update({"text": "", "truncated": True})
    return row


class Kids:
    """The owner's A14bc answer and his C20 answer, as the classifier left them."""

    def __init__(self, case: unittest.TestCase) -> None:
        self.vault = Vault(case)
        self.root = self.vault.root
        self.vault.owner_birth()
        self.harvey = self.vault.claim("A14bc", A14BC, label="Harvey's swimming classes",
                                       subject="Harvey")["event_ref"]
        self.james = self.vault.claim("A14bc", A14BC, label="Going to James's baseball games",
                                      subject="James Everett Taylor")["event_ref"]
        self.vault.publish()
        self.chunks = 0

    def chunk(self, text: str = CHUNK, *, name: str = "") -> str:
        """One archive chunk the classify backfill just filed."""
        self.chunks += 1
        folder = self.root / "sources" / "archive"
        folder.mkdir(parents=True, exist_ok=True)
        stem = name or f"chunk-{self.chunks:03d}"
        (folder / f"{stem}.md").write_text(f"---\ntitle: {stem}\ntype: archive\n---\n\n{text}\n", "utf-8")
        return f"sources/archive/{stem}.md"

    def plan(self, hint: str | None = None, **kwargs) -> dict:
        """Leg A exactly as the hosted worker runs it: `--limit 1 --source <hint>`."""
        return resolver.plan_items(self.root, limit=kwargs.pop("limit", 1),
                                   only_sources={hint} if hint else None, **kwargs)

    def file(self, item: dict, answers: list[dict], **kwargs) -> dict:
        """Leg C exactly as the hosted worker runs it: a fresh read, the envelope alone."""
        return resolver.file_envelope(self.root, envelope(item, answers), now=NOW, **kwargs)

    def ledger(self) -> dict:
        return resolver.load_ledger(self.root).get("nodes") or {}

    def settle(self) -> None:
        """The morning's first filing: both moments estimated, Harvey's placed
        (35 months), James's a month point (the 07:47 filing's 2018-01)."""
        item = self.plan()["items"][0]
        self.file(item, [unknown(self.harvey, estimate=estimate("2023-10", "2026-08")),
                         unknown(self.james, estimate=estimate("2018-01", "2018-01", "related_moment"))])

    def corrections(self) -> list[str]:
        folder = self.root / "sources" / "corrections"
        return sorted(p.name for p in folder.glob("*.md")) if folder.is_dir() else []

    def snapshot(self) -> dict:
        """Everything a churn round would move, byte for byte."""
        state = self.root / "state"
        return {
            "corrections": self.corrections(),
            "receipts": sorted(p.relative_to(state).as_posix()
                               for p in (state / "temporal_claims" / "receipts").rglob("*.json")),
            "ledger": hashlib.sha256((state / "resolver" / "resolutions.json").read_bytes()).hexdigest(),
            "projection": hashlib.sha256(
                (state / "temporal_claims" / "calculated-timeline.json").read_bytes()).hexdigest(),
        }

    def active_estimates(self, node_id: str) -> list[str]:
        return [c["claim_id"] for c in ts.fold_active_index(self.root)["claims"]
                if c.get("event_ref") == node_id and c.get("status") == "active"
                and str(c.get("extractor_version", "")).startswith("resolver/")
                and (c.get("temporal_value") or {}).get("confidence") == "conjectural"]

    def node(self, node_id: str) -> dict:
        return next(n for n in pub.read_projection(self.root)["nodes"] if n["node_id"] == node_id)


# --------------------------------------------------------------------------
# The incident: three chains, one selection
# --------------------------------------------------------------------------


class ThreeChainsOneSelectionTests(unittest.TestCase):
    """07:30, 07:35 and 07:40 each committed an archive chunk; each started a
    hop-0 chain; each chain's leg A planned A14bc (James's row was
    `no_answer_returned`, attempts 1) from the same ledger; they filed at
    07:47, 07:54 and 08:10 with three different guesses."""

    def setUp(self):
        self.kids = Kids(self)
        # The row the three chains all read: James came back silent once.
        first = self.kids.plan()["items"][0]
        self.kids.file(first, [unknown(self.kids.harvey, estimate=estimate("2023-10", "2026-08"))])
        self.assertEqual(self.kids.ledger()[self.kids.james]["status"], "no_answer_returned")
        hints = [self.kids.chunk() for _ in range(3)]
        self.items = [self.kids.plan(hint)["items"][0] for hint in hints]

    def test_all_three_chains_plan_the_same_item(self):
        self.assertEqual({item["key"] for item in self.items}, {self.items[0]["key"]})
        self.assertEqual(self.items[0]["node_ids"], [self.kids.james])

    def test_only_the_first_envelope_files(self):
        guesses = [("2018-01", "2018-01"), ("2018-05", "2018-05"), ("2019-05", "2019-05")]
        first = self.kids.file(self.items[0], [unknown(self.kids.james,
                                                       estimate=estimate(*guesses[0], "related_moment"))])
        self.assertEqual(first["placed_by_estimate"], 1)
        before = self.kids.snapshot()
        for item, guess in zip(self.items[1:], guesses[1:]):
            report = self.kids.file(item, [unknown(self.kids.james, estimate=estimate(*guess, "related_moment"))])
            self.assertEqual([row["reason"] for row in report["refused_items"]], ["stale_targets"])
            self.assertEqual((report["filed"], report["estimates"], report["placed_by_estimate"]), (0, 0, 0))
        self.assertEqual(self.kids.snapshot(), before)
        self.assertEqual(self.kids.corrections(), [])
        self.assertEqual(self.kids.ledger()[self.kids.james]["placed_by_estimate"]["record"]["best"], "2018-01")

    def test_a_silent_late_envelope_does_not_wipe_the_filed_estimate(self):
        """04:34's shape: a chain bought before the estimate came back silent and
        rewrote the row to `no_answer_returned` — orphaning the filed claim."""
        self.kids.file(self.items[0], [unknown(self.kids.james, estimate=estimate("2018-01", "2018-01", "related_moment"))])
        row = self.kids.ledger()[self.kids.james]
        report = resolver.file_envelope(self.kids.root, silent(self.items[1]), now=NOW)
        self.assertEqual([r["reason"] for r in report["refused_items"]], ["stale_targets"])
        self.assertEqual(self.kids.ledger()[self.kids.james], row)
        self.assertEqual(self.kids.active_estimates(self.kids.james), [row["placed_by_estimate"]["claim_id"]])

    def test_before_the_rules_the_second_envelope_filed_a_correction(self):
        """The counterfactual, so the guard above is known to catch the incident."""
        self.kids.file(self.items[0], [unknown(self.kids.james, estimate=estimate("2018-01", "2018-01", "related_moment"))])
        v360_digest = resolver._targets_digest
        with mock.patch.object(resolver, "_targets_digest",
                               lambda ids, by_node, ledger=None: v360_digest(ids, by_node)), \
                mock.patch.object(resolver, "a_guess_replaces_the_standing_one", lambda *a, **k: True):
            # Re-plan the pre-rule identities, as v360 would have minted them.
            report = self.kids.file({**self.items[1], "identity": {
                **self.items[1]["identity"],
                "targets_digest": v360_digest(self.items[1]["node_ids"], resolver._Read(self.kids.root).by_node)}},
                [unknown(self.kids.james, estimate=estimate("2018-05", "2018-05", "related_moment"))])
        self.assertEqual(report["placed_by_estimate"], 1)
        self.assertEqual(len(self.kids.corrections()), 1)


# --------------------------------------------------------------------------
# An estimate is revisited only by a dated story
# --------------------------------------------------------------------------


class AnEstimateIsRevisitedOnlyByADatedStoryTests(unittest.TestCase):

    def setUp(self):
        self.kids = Kids(self)
        self.kids.settle()
        ledger = self.kids.ledger()
        self.assertTrue(all(resolver._placed_by_estimate(ledger[n]) for n in (self.kids.harvey, self.kids.james)))

    def test_the_vault_wide_fallback_never_replans_an_estimated_moment(self):
        hint = self.kids.chunk()
        read = resolver._Read(self.kids.root, triggers={hint})
        self.assertIn(self.kids.james, read.by_node, "reachable, so a dated story can still sharpen it")
        self.assertEqual(read.revisit, {}, "an undated chunk sharing its words re-opens nothing")
        plan = self.kids.plan(hint, limit=50)
        planned = {n for item in plan["items"] for n in item["node_ids"]}
        self.assertFalse(planned & {self.kids.harvey, self.kids.james})
        self.assertTrue(plan["complete"])

    def test_even_a_row_that_says_no_answer_returned_is_not_replanned(self):
        """The shape a v360 silent envelope could leave behind."""
        ledger = resolver.load_ledger(self.kids.root)
        row = ledger["nodes"][self.kids.james]
        row.update({"status": "no_answer_returned", "attempts": 1})
        resolver.save_ledger(self.kids.root, ledger)
        self.assertFalse(self.kids.plan(limit=50)["items"])

    def test_a_dated_story_revisits_and_sharpens(self):
        story = self.kids.chunk(LITTLE_LEAGUE, name="little-league")
        read = resolver._Read(self.kids.root, triggers={story})
        self.assertEqual(read.revisit, {self.kids.james: {"trigger": story, "why": "retrieval"}})
        item = next(i for i in self.kids.plan(story, limit=5)["items"] if i["node_ids"] == [self.kids.james])
        self.assertEqual(item["include_paths"], [story])
        standing = self.kids.ledger()[self.kids.james]["placed_by_estimate"]["claim_id"]
        report = resolver.file_envelope(self.kids.root, {**envelope(item, [{
            "node_id": self.kids.james, "answer": {"earliest": "2019-04", "latest": "2019-04"},
            "basis": "stated", "confidence": 0.9, "fact_key": "james_baseball_games", "reason": "x",
            "question": None, "citations": [{"doc": f"{story}#p0",
                                             "quote": "James started Little League baseball in April 2019"}]}])},
            now=NOW)
        self.assertEqual(report["filed"], 1)
        self.assertNotIn(standing, self.kids.active_estimates(self.kids.james))
        self.assertEqual(self.kids.node(self.kids.james)["best_temporal_value"]["best"], "2019-04")

    def test_a_dated_story_may_move_the_estimate(self):
        story = self.kids.chunk(LITTLE_LEAGUE, name="little-league")
        item = next(i for i in self.kids.plan(story, limit=5)["items"] if i["node_ids"] == [self.kids.james])
        report = self.kids.file(item, [unknown(self.kids.james, estimate=estimate("2019-03", "2019-05", "related_moment"))])
        self.assertEqual(report["placed_by_estimate"], 1)
        self.assertEqual(self.kids.ledger()[self.kids.james]["placed_by_estimate"]["record"]["best"], "2019-03/2019-05")
        self.assertEqual(len(self.kids.active_estimates(self.kids.james)), 1)

    def test_each_dated_story_revisits_once(self):
        story = self.kids.chunk(LITTLE_LEAGUE, name="little-league")
        item = next(i for i in self.kids.plan(story, limit=5)["items"] if i["node_ids"] == [self.kids.james])
        self.kids.file(item, [unknown(self.kids.james, estimate=estimate("2018-02", "2018-02", "related_moment"))])
        self.assertEqual(resolver._Read(self.kids.root, triggers={story}).revisit, {})


# --------------------------------------------------------------------------
# A guess never replaces a guess
# --------------------------------------------------------------------------


class AGuessNeverReplacesAGuessTests(unittest.TestCase):

    def setUp(self):
        self.kids = Kids(self)
        self.kids.settle()
        self.item = self.kids.plan(force=True, limit=5)["items"][0]
        self.before = self.kids.snapshot()

    def test_a_noisy_reestimate_files_nothing(self):
        report = self.kids.file(self.item, [
            unknown(self.kids.james, estimate=estimate("2018-05", "2018-05", "related_moment")),
            unknown(self.kids.harvey, estimate=estimate("2023-06", "2026-08"))], force=True)
        self.assertEqual((report["estimates"], report["placed_by_estimate"]), (0, 0))
        self.assertEqual(report["outcomes"], {"kept_estimate": 2})
        self.assertEqual(self.kids.snapshot(), self.before)

    def test_a_wider_undated_guess_does_not_retire_the_standing_one(self):
        report = self.kids.file(self.item, [unknown(self.kids.james, estimate=estimate("2019-05", "2026-08"))],
                                force=True)
        self.assertEqual(report["outcomes"]["kept_estimate"], 1)
        self.assertEqual(self.kids.snapshot()["corrections"], [])
        self.assertTrue(self.kids.node(self.kids.james)["usable_placement"])

    def test_a_narrower_estimate_does_replace(self):
        standing = self.kids.ledger()[self.kids.harvey]["placed_by_estimate"]["claim_id"]
        report = self.kids.file(self.item, [unknown(self.kids.harvey, estimate=estimate("2024-01", "2024-12"))],
                                force=True)
        self.assertEqual(report["placed_by_estimate"], 1)
        self.assertEqual(len(self.kids.corrections()), 1)
        [active] = self.kids.active_estimates(self.kids.harvey)
        self.assertNotEqual(active, standing)
        self.assertEqual(self.kids.node(self.kids.harvey)["best_temporal_value"]["best"], "2024-01/2024-12")

    def test_narrower_means_inside_and_materially_so(self):
        standing = {"earliest": "2023-10", "latest": "2026-08"}
        self.assertTrue(resolver.estimate_is_materially_narrower(standing, {"earliest": "2024-01", "latest": "2024-12"}))
        self.assertFalse(resolver.estimate_is_materially_narrower(standing, {"earliest": "2019-01", "latest": "2019-06"}),
                         "narrower but outside is a different guess, not a sharper one")
        self.assertFalse(resolver.estimate_is_materially_narrower(standing, {"earliest": "2023-11", "latest": "2026-08"}),
                         "one month off the edge is noise")
        self.assertFalse(resolver.estimate_is_materially_narrower({"earliest": "2018-01", "latest": "2018-01"},
                                                                  {"earliest": "2018-05", "latest": "2018-05"}))
        self.assertTrue(resolver.estimate_is_materially_narrower({"earliest": "2018", "latest": "2018"},
                                                                 {"earliest": "2018-03", "latest": "2018-05"}))

    def test_a_silent_reask_leaves_every_row_as_it_stood(self):
        rows = self.kids.ledger()
        report = resolver.file_envelope(self.kids.root, silent(self.item), now=NOW, force=True)
        self.assertEqual(report["outcomes"], {"no_answer_returned": 2})
        self.assertEqual(self.kids.ledger(), rows)
        self.assertEqual(self.kids.snapshot(), self.before)


# --------------------------------------------------------------------------
# The planner, run over and over while the backfill classifies
# --------------------------------------------------------------------------


class ZeroChurnTests(unittest.TestCase):
    """Twelve backfill rounds; each files an undated archive chunk and starts
    THREE chains that plan at the same ledger and file one after another, with
    a model that guesses a different month every call and goes silent every
    fourth (starting with the very first purchase). Once each moment has its
    reading, nothing moves again."""

    GUESSES = itertools.cycle([("2018-01", "2018-01"), ("2018-05", "2018-05"), ("2019-05", "2019-05"),
                               ("2023-10", "2026-08"), ("2017-09", "2018-02")])

    def model(self, item: dict) -> dict:
        self.calls += 1
        if self.calls % 4 == 1:
            return silent(item)
        return envelope(item, [unknown(node_id, estimate=estimate(*next(self.GUESSES), "related_moment"))
                               for node_id in item["node_ids"]])

    def test_the_planner_run_repeatedly_churns_nothing(self):
        kids = Kids(self)
        c20 = [kids.vault.claim("C20", C20, label=label, subject=subject)["event_ref"]
               for label, subject in (("James Everett moved between baseball teams", "James Everett Taylor"),
                                      ("Charlee moved from football to track", "Charlee"))]
        kids.vault.publish()
        moments = [kids.harvey, kids.james, *c20]
        self.calls = 0
        snapshots, filings, planned = [], [], []
        for _round in range(12):
            hints = [kids.chunk() for _ in range(3)]
            # All three chains plan before any of them files: the hosted race.
            items = [item for hint in hints for item in kids.plan(hint)["items"]]
            planned.append(len(items))
            filed = 0
            for item in items:
                report = resolver.file_envelope(kids.root, self.model(item), now=NOW)
                filed += report["filed"] + report["estimates"] + report["placed_by_estimate"]
            filings.append(filed)
            snapshots.append(kids.snapshot())
        ledger = kids.ledger()
        # Every moment reached a settled reading within the bounded retries.
        self.assertTrue(all(ledger[n]["status"] in ("unknown", "no_answer_returned") for n in moments))
        # No estimate was ever retired and refiled: not one correction.
        self.assertEqual(kids.corrections(), [])
        # Every filed estimate is owned by its ledger row, and there is one per moment.
        for node_id in moments:
            owned = (ledger[node_id].get("placed_by_estimate") or {}).get("claim_id")
            self.assertEqual(kids.active_estimates(node_id), [owned] if owned else [])
        # And the second half of the backfill moved nothing at all.
        self.assertEqual(len({json.dumps(s, sort_keys=True) for s in snapshots[6:]}), 1)
        self.assertEqual(filings[6:], [0] * 6)
        self.assertEqual(planned[6:], [0] * 6, "a settled vault plans nothing")
        # Each round's first envelope is the only one that files; the others
        # of the same selection are stale.
        self.assertLessEqual(sum(1 for f in filings if f), 2 * 2, "two stories, at most two readings each")


# --------------------------------------------------------------------------
# His answer is the placement: the Charlee card
# --------------------------------------------------------------------------


class HisAnswerPlacesTheCharleeCardTests(unittest.TestCase):
    """C20's "Charlee moved from football to track": the resolver estimated it
    2019–2021-10 from "going to track meets around 11 October 2021", and the
    card asked "What year did Charlee switch from flag football to track?"."""

    def setUp(self):
        self.vault = Vault(self)
        self.vault.owner_birth()
        self.node = self.vault.claim("C20", C20, label="Charlee moved from football to track",
                                     subject="Charlee")["event_ref"]
        self.vault.publish()
        item = resolver.plan_items(self.vault.root, limit=5)["items"][0]
        question = "What year did Charlee switch from flag football to track?"
        # The first reading: unknown, a window that does not place (story basis), a card.
        resolver.file_envelope(self.vault.root, envelope(item, [unknown(
            self.node, question=question, estimate=estimate("2019", "2021-10", "story", 0.4))]), now=NOW)
        self.card = next(row for row in self.vault.cards() if row.get("node_ref") == self.node)
        self.assertEqual(self.card["prompt_intent"], question)

    def answer(self) -> str:
        source = ts.promote_conversational_source(self.vault.root, CHARLEE_ANSWER, {
            "turn_ref": "0", "speaker": "person", "channel": "web",
            "session_ref": f"conversation:cand:work_item:{self.card['work_item_id']}"})
        return source.source_path

    def test_the_reply_is_read_as_the_date_he_said(self):
        reading = ap.answer_reading(CHARLEE_ANSWER)
        self.assertEqual((reading["reading"], reading["temporal_value"]["best"]), (ap.READING_DATE, "2026-01"))

    def test_his_answer_places_it_over_the_estimate(self):
        self.answer()
        report = ap.place_answers(self.vault.root, now=NOW)
        [filed] = report["filed"]
        self.assertEqual((filed["node_ref"], filed["reading"]), (self.node, ap.READING_DATE))
        self.vault.publish()
        node = next(n for n in pub.read_projection(self.vault.root)["nodes"] if n["node_id"] == self.node)
        self.assertEqual((node["best_temporal_value"]["best"], node["best_temporal_value"]["basis"]),
                         ("2026-01", "stated"))
        self.assertNotIn("probable_window", node)
        self.assertFalse(any(row.get("node_ref") == self.node for row in self.vault.cards()))

    def test_his_answer_wins_over_a_placed_estimate_and_retires_it(self):
        # The estimate that DOES place (related_moment, 34 months) — filed as the
        # system's inference before he answered.
        item = resolver.plan_items(self.vault.root, limit=5, force=True)["items"][0]
        resolver.file_envelope(self.vault.root, envelope(item, [unknown(
            self.node, estimate=estimate("2019-01", "2021-10", "related_moment", 0.4))]), now=NOW, force=True)
        estimate_claim = resolver.load_ledger(self.vault.root)["nodes"][self.node]["placed_by_estimate"]["claim_id"]
        path = self.answer()
        ap.place_answers(self.vault.root, now=NOW)
        self.vault.publish()
        node = next(n for n in pub.read_projection(self.vault.root)["nodes"] if n["node_id"] == self.node)
        self.assertEqual((node["best_temporal_value"]["best"], node["best_temporal_value"]["basis"]),
                         ("2026-01", "stated"), "a system inference never overrides him")
        # His reply carries a date, so it re-opens the estimated moment, and a
        # verified answer from his words retires the guess.
        read = resolver._Read(self.vault.root, triggers={path})
        self.assertIn(self.node, read.revisit)
        item = next(i for i in resolver.plan_items(self.vault.root, limit=5, only_sources={path}, read=read)["items"]
                    if self.node in i["node_ids"])
        resolver.file_envelope(self.vault.root, envelope(item, [{
            "node_id": self.node, "answer": {"earliest": "2026-01", "latest": "2026-01"}, "basis": "stated",
            "confidence": 0.95, "fact_key": "charlee_football_to_track", "reason": "he said so",
            "question": None, "citations": [{"doc": f"{path}#p0", "quote": CHARLEE_ANSWER}]}]), now=NOW)
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.vault.root)["claims"]}
        self.assertEqual(by_id[estimate_claim]["status"], "superseded")
        node = next(n for n in pub.read_projection(self.vault.root)["nodes"] if n["node_id"] == self.node)
        self.assertEqual((node["best_temporal_value"]["best"], node["conflict_state"]), ("2026-01", "none"))

    def test_a_reply_naming_an_ordering_or_two_dates_stays_a_telling(self):
        for text in ("after Dad died in 2021 she switched", "somewhere between 2019 and 2021",
                     "We lived at 1998 Elm Street then", "we drove 2000 miles to her meets"):
            with self.subTest(text=text):
                self.assertIsNone(ap.date_in_words(text))
        for text, best in (("She graduated in 2006.", "2006"), ("around 2005 I think", "2005~"),
                           ("in the spring of 1998", "1998-21")):
            with self.subTest(text=text):
                self.assertEqual(ap.date_in_words(text).best, best)


class TheRulesAreNamedTests(unittest.TestCase):

    def test_every_rule_is_a_named_sentence(self):
        for rule in (resolver.A_PLAN_IS_FILED_AGAINST_THE_LEDGER_IT_READ,
                     resolver.AN_ESTIMATE_IS_REVISITED_ONLY_BY_A_DATED_STORY,
                     resolver.A_GUESS_NEVER_REPLACES_A_GUESS,
                     resolver.A_SILENCE_NEVER_UNSETTLES_A_READING,
                     ap.A_DATE_HE_SAID_IN_A_SENTENCE_IS_A_DATE_HE_SAID):
            self.assertIsInstance(rule, str)
            self.assertGreater(len(rule), 40)


if __name__ == "__main__":
    unittest.main()
