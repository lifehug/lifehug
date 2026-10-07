"""Intake — the terminal front door (lifehug#469, v398).

The phase runner takes an injected :class:`intake.Runner`, so every
subprocess here is scripted; the ASKING phase runs over a REAL proposal
written by `landmark_offer.propose` in a synthetic vault, so the cards are
the cards a person would see. Synthetic data only; NEVER references
~/Workspace/dave.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import intake  # noqa: E402
import landmark_offer as lo  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_landmark_offer import (  # noqa: E402
    ScriptedCall, read_dates, read_unit, reading, synthetic_vault,
)

NOW = "2026-10-06T12:00:00Z"

LETTER = ("Dad wrote on 7 June 2002 that David would be home on Willow Street "
          "from July 2002, and that the Orchard House had been theirs from "
          "August 1982 to June 1986.")


class FakeRunner(intake.Runner):
    """Scripts every subprocess; records what was asked."""

    def __init__(self, vault_root: Path, *, ready: bool = False,
                 proposal: dict | None = None, port_open: bool = True) -> None:
        super().__init__(vault_root)
        self.ready = ready
        self.proposal = proposal
        self.port = port_open
        self.calls: list[list[str]] = []
        self.git_calls: list[list[str]] = []
        self.spawned = 0
        self.ai_calls: list[str] = []
        self.emitted_tasks: list[dict] = []
        self.push_fail_times = 0
        # A queued compile whose fixed wait runs out: the job states to report.
        self.compile_wait_times_out = False
        self.job_states: list[dict] = []
        self.slept = 0.0

    def writer_lock(self):
        import contextlib
        self.locks = getattr(self, "locks", 0) + 1
        return contextlib.nullcontext()

    def job_state(self, job_id):
        return self.job_states.pop(0) if self.job_states else {}

    def sleep(self, seconds):
        self.slept += seconds

    def provider_ready(self):
        return self.ready, "fake-model"

    def port_open(self, host, port):
        return self.port

    def spawn_viewer(self, host, port):
        self.spawned += 1
        self.port = True

    def call_ai(self, prompt, model):
        self.ai_calls.append(prompt)
        if "READ ALL" in prompt.upper() or "reading" in prompt.lower():
            return json.dumps({"units": [], "events": [], "stories": [], "unplaced": []})
        return json.dumps({"people": [], "events": [], "themes": []})

    def git(self, *args):
        self.git_calls.append(list(args))
        if args[0] == "diff":
            return intake.Result(1)  # something is staged
        if args[0] == "push" and self.push_fail_times > 0:
            self.push_fail_times -= 1
            return intake.Result(1, "", "! [rejected] non-fast-forward")
        return intake.Result(0)

    def lifehug(self, *args, stdin=None):
        self.calls.append(list(args))
        verb = args[0]
        if verb == "ingest-story":
            kind = ("witness account from X" if "--witness" in args
                    else "third-party record (r)" if "--record" in args else "story")
            return intake.Result(0, f"✓ Ingested {kind}: sources/manual/2026-10-06-test.md\n")
        if verb == "landmark-offer" and "--prompts" in args:
            return intake.Result(0, json.dumps({"reading": {"prompt": "READ ALL the text", "model": "reader"}}))
        if verb == "landmark-offer" and "--completions" in args:
            return intake.Result(0, json.dumps(self.proposal or {
                "proposal_id": "lmo:abc", "state": "proposed", "units": []}))
        if verb == "landmark-offer" and "--apply" in args:
            return intake.Result(0, "Queued x\n" + json.dumps({
                "receipt_id": "lmr:feed", "sentence": "one stay placed"}))
        if verb == "classify-story" and "--prompt" in args:
            return intake.Result(0, "CLASSIFY this source\n")
        if verb == "classify-story" and "--from-response" in args:
            return intake.Result(0, "filed\n")
        if verb == "compile" and "--emit-tasks" in args:
            Path(args[2]).write_text(json.dumps(self.emitted_tasks), encoding="utf-8")
            return intake.Result(0, f"✓ Emitted {len(self.emitted_tasks)} synthesis task(s)\n")
        if verb == "compile" and self.compile_wait_times_out:
            return intake.Result(1, "Queued compile job j123\n",
                                 "Error: local job could not complete (timed out)\n")
        if verb == "compile":
            return intake.Result(0, "✓ Wiki compile complete: 3 page updates\n")
        return intake.Result(1, "", f"unexpected {args}")


class IntakeCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="intake-")
        self._ctx = synthetic_vault(tmp)
        self.root = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)
        self.lines: list[str] = []

    def say(self, line: str) -> None:
        self.lines.append(str(line))

    def file_stay(self, label: str, start: str, end: str) -> None:
        timeline.save_landmark("residences", {
            "domain": "residences", "label": label, "city": "Orchard City",
            "span": {"start": chrono.parse_edtf(start).to_dict(),
                     "end": chrono.parse_edtf(end).to_dict()}})

    def real_proposal(self, *, evidence: str | None = "relative",
                      evidence_source: str | None = "witness:dad") -> dict:
        """A proposal from the REAL reader over LETTER: one revision (Orchard
        House start) and one new stay (Willow Street from July 2002)."""
        self.file_stay("Orchard House", "1982-08", "1986-06")
        units = [
            read_unit("u1", "residences", "Orchard House", LETTER,
                      record={"label": "Orchard House", "city": "Orchard City"},
                      dates=read_dates("1982-08", "1986-06")),
            read_unit("u2", "residences", "Willow Street", LETTER,
                      record={"label": "Willow Street", "city": "Orchard City"},
                      dates=read_dates("2002-07", None)),
        ]
        return lo.propose(LETTER, self.root, call=ScriptedCall(reading=reading(units=units)),
                          now=NOW, evidence=evidence, evidence_source=evidence_source)

    def start(self, runner: FakeRunner, **kwargs) -> tuple[dict, bool]:
        defaults = {"kind": "witness", "witness": "Dad", "title": "Dad's letter",
                    "runner": runner, "say": self.say, "now": NOW}
        defaults.update(kwargs)
        return intake.start(self.root, LETTER, **defaults)


# --------------------------------------------------------------------------
# Pure parts
# --------------------------------------------------------------------------

class RecordTests(IntakeCase):
    def test_a_witness_is_relative_evidence_and_a_record_a_document_by_default(self):
        witness = intake.new_record(kind="witness", text="x", title=None, witness="Mom",
                                    record_ref=None, evidence=None, evidence_source=None,
                                    source_label="cli", plan=False, yes=False, no_serve=True,
                                    no_push=True, cap=6, now=NOW)
        self.assertEqual(witness["evidence"], "relative")
        self.assertEqual(witness["evidence_source"], "witness:mom")
        record = intake.new_record(kind="record", text="x", title=None, witness=None,
                                   record_ref="letters:itinerary", evidence=None,
                                   evidence_source=None, source_label="cli", plan=False,
                                   yes=False, no_serve=True, no_push=True, cap=6, now=NOW)
        self.assertEqual(record["evidence"], "document")
        self.assertEqual(record["evidence_source"], "letters:itinerary")
        story = intake.new_record(kind="story", text="x", title=None, witness=None,
                                  record_ref=None, evidence=None, evidence_source=None,
                                  source_label="cli", plan=False, yes=False, no_serve=True,
                                  no_push=True, cap=6, now=NOW)
        self.assertIsNone(story["evidence"])
        self.assertEqual(list(story["phases"]), list(intake.PHASES))

    def test_a_story_cannot_claim_evidence_and_a_record_needs_a_ref(self):
        with self.assertRaises(intake.IntakeError):
            intake.new_record(kind="story", text="x", title=None, witness=None,
                              record_ref=None, evidence="document", evidence_source=None,
                              source_label="cli", plan=False, yes=False, no_serve=True,
                              no_push=True, cap=6)
        with self.assertRaises(intake.IntakeError):
            intake.new_record(kind="record", text="x", title=None, witness=None,
                              record_ref=None, evidence=None, evidence_source=None,
                              source_label="cli", plan=False, yes=False, no_serve=True,
                              no_push=True, cap=6)


class CardTests(IntakeCase):
    def test_cards_name_what_each_unit_is_over_a_real_proposal(self):
        proposal = self.real_proposal()
        cards = intake.cards_from_proposal(proposal)
        kinds = {card["subject"]: card["kind"] for card in cards}
        self.assertEqual(kinds, {"Orchard House": "duplicate", "Willow Street": "new"})
        # Now the letter moves the start: the same stay becomes a revision.
        self.file_stay("Orchard House", "1982-06", "1986-06")
        proposal = lo.propose(LETTER, self.root, call=ScriptedCall(reading=reading(units=[
            read_unit("u1", "residences", "Orchard House", LETTER,
                      record={"label": "Orchard House", "city": "Orchard City"},
                      dates=read_dates("1982-08", "1986-06"))])), now=NOW,
            evidence="document", evidence_source="letters:grandma")
        cards = intake.cards_from_proposal(proposal)
        self.assertEqual(cards[0]["kind"], "revision")
        self.assertIn("revises residences/orchard house start", cards[0]["text"])
        self.assertEqual(intake.card_counts(cards),
                         {"new": 0, "revision": 1, "conflict": 0, "duplicate": 0})

    def test_conflict_outranks_revision_outranks_duplicate(self):
        unit = {"unit_id": "lmu:1", "conflicts": [{"kind": "overlapping_span"}],
                "revises": [{"bound": "start"}], "duplicates": ["x"]}
        self.assertEqual(intake.card_kind(unit), "conflict")
        unit["conflicts"] = []
        self.assertEqual(intake.card_kind(unit), "revision")
        unit["revises"] = []
        self.assertEqual(intake.card_kind(unit), "duplicate")
        unit["duplicates"] = []
        self.assertEqual(intake.card_kind(unit), "new")


class DecisionTests(unittest.TestCase):
    CARDS = [{"unit_id": "lmu:new", "kind": "new"},
             {"unit_id": "lmu:rev", "kind": "revision"},
             {"unit_id": "lmu:con", "kind": "conflict"},
             {"unit_id": "lmu:dup", "kind": "duplicate"}]

    def test_yes_files_only_new_never_a_revision_or_conflict(self):
        self.assertEqual(intake.decide_units(self.CARDS, yes=True), ["lmu:new"])
        self.assertEqual(intake.decide_units(self.CARDS, all_new=True), ["lmu:new"])

    def test_an_explicit_list_is_the_yes_and_none_is_none(self):
        self.assertEqual(intake.decide_units(self.CARDS, units=["lmu:rev", "lmu:new"]),
                         ["lmu:rev", "lmu:new"])
        self.assertEqual(intake.decide_units(self.CARDS, none=True, yes=True), [])
        with self.assertRaises(intake.IntakeError):
            intake.decide_units(self.CARDS, units=["lmu:nope"])

    def test_nothing_decided_files_nothing(self):
        self.assertEqual(intake.decide_units(self.CARDS), [])


class ScopeTests(unittest.TestCase):
    def test_only_tasks_citing_this_source_and_at_most_the_cap(self):
        tasks = [{"slug": f"p{i}", "sources": [{"id": "manual:x", "source": "sources/manual/x.md"}]}
                 for i in range(10)]
        tasks.append({"slug": "other", "sources": [{"id": "answer:A1", "source": "answers/A1.md"}]})
        scoped = intake.scope_tasks(tasks, source_path="sources/manual/x.md",
                                    source_id="manual:x", cap=6)
        self.assertEqual([t["slug"] for t in scoped], [f"p{i}" for i in range(6)])
        self.assertEqual(intake.scope_tasks(tasks, source_path=None, source_id=None, cap=6), [])
        self.assertEqual(intake.DEFAULT_SYNTHESIS_CAP, 6)


# --------------------------------------------------------------------------
# The phases, scripted
# --------------------------------------------------------------------------

class KeylessFlowTests(IntakeCase):
    def test_keyless_stops_at_the_reading_and_continues_through_to_the_report(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=False, proposal=proposal, port_open=False)
        runner.emitted_tasks = [
            {"slug": "dad", "narrative_path": str(self.root / "state/synthesis/dad.md"),
             "sources": [{"id": "manual:2026-10-06-test", "source": "sources/manual/2026-10-06-test.md"}]},
            {"slug": "elsewhere", "narrative_path": str(self.root / "state/synthesis/elsewhere.md"),
             "sources": [{"id": "answer:A1", "source": "answers/A1.md"}]},
        ]
        record, finished = self.start(runner, no_push=True)
        self.assertFalse(finished)
        self.assertEqual(record["phases"]["preflight"]["status"], "done")
        self.assertEqual(runner.spawned, 1)
        self.assertEqual(record["phases"]["filing"]["source_path"], "sources/manual/2026-10-06-test.md")
        self.assertEqual(record["phases"]["reading"]["status"], "waiting")
        self.assertIn("intake: reading needs the reading completion", "\n".join(self.lines))
        self.assertTrue(any(line.startswith("next: python3 system/lifehug.py intake continue ")
                            for line in self.lines))
        # The reading prompt went through the evidence flags.
        prompts_call = next(c for c in runner.calls if "--prompts" in c)
        self.assertIn("--evidence", prompts_call)
        self.assertEqual(prompts_call[prompts_call.index("--evidence") + 1], "relative")
        self.assertEqual(prompts_call[prompts_call.index("--evidence-source") + 1], "witness:dad")

        # The agent writes the completion and continues: asking waits.
        folder = intake.intake_dir(self.root, record["id"])
        completion = folder / "reading.completion.json"
        completion.write_text(json.dumps({"reading": {"units": []}}), encoding="utf-8")
        again = intake.Intake(self.root, intake.load_intake(self.root, record["id"]),
                              runner=runner, say=self.say)
        self.assertFalse(again.run(completions=completion))
        self.assertEqual(again.record["phases"]["reading"]["status"], "done")
        self.assertEqual(again.record["phases"]["asking"]["status"], "waiting")
        counts = again.record["phases"]["asking"]["counts"]
        self.assertEqual(counts["new"], 1)
        self.assertEqual(counts["duplicate"], 1)
        self.assertIn("[new]", "\n".join(self.lines))

        # The owner names the unit; landmarks file; classifying waits.
        new_id = next(c["unit_id"] for c in again.record["phases"]["asking"]["cards"] if c["kind"] == "new")
        third = intake.Intake(self.root, intake.load_intake(self.root, record["id"]),
                              runner=runner, say=self.say)
        self.assertFalse(third.run(units=[new_id]))
        self.assertEqual(third.record["phases"]["landmarks"]["receipt_id"], "lmr:feed")
        apply_call = next(c for c in runner.calls if "--apply" in c)
        self.assertEqual(apply_call[apply_call.index("--units") + 1], new_id)
        self.assertIn("undo: python3 system/lifehug.py landmark-offer --retract lmr:feed",
                      self.lines)
        self.assertEqual(third.record["phases"]["classifying"]["status"], "waiting")

        # Classification response in; compiling waits for the ONE scoped draft.
        response = folder / "classify.response.json"
        response.write_text("{}", encoding="utf-8")
        fourth = intake.Intake(self.root, intake.load_intake(self.root, record["id"]),
                               runner=runner, say=self.say)
        self.assertFalse(fourth.run(response=response))
        compiling = fourth.record["phases"]["compiling"]
        self.assertEqual(compiling["status"], "waiting")
        self.assertEqual(compiling["tasks"], ["dad"])

        # The draft is written; the rest runs to the report.
        (self.root / "state" / "synthesis").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "synthesis" / "dad.md").write_text("Dad wrote.\n", encoding="utf-8")
        fifth = intake.Intake(self.root, intake.load_intake(self.root, record["id"]),
                              runner=runner, say=self.say)
        self.assertTrue(fifth.run())
        self.assertTrue(fifth.record["done"])
        self.assertEqual(fifth.record["phases"]["compiling"]["updates"], 3)
        # Both compiles are model-free: the cap is the only synthesis.
        compiles = [c for c in runner.calls if c[0] == "compile"]
        self.assertTrue(all("--emit-tasks" in c or c == ["compile", "--no-ai"] for c in compiles),
                        compiles)
        self.assertIn(["compile", "--no-ai"], compiles)
        self.assertIn("1 other page(s) wait for the next compile", "\n".join(self.lines))
        self.assertEqual(fifth.record["phases"]["pushing"]["committed"], True)
        self.assertEqual(fifth.record["phases"]["pushing"]["pushed"], False)
        report = "\n".join(self.lines)
        self.assertIn("intake: done", report)
        self.assertIn("/source-actions?ref=sources/manual/2026-10-06-test.md", report)
        self.assertIn("receipt lmr:feed", report)
        self.assertIn("/views/timeline", report)
        self.assertIn("wiki       dad", report)
        phases = [line.split()[1] for line in self.lines
                  if line.startswith("intake: ") and line.endswith(" …")]
        self.assertEqual(phases, ["preflight", "filing", "reading", "asking",
                                  "landmarks", "classifying", "compiling", "pushing"])

    def test_yes_never_files_a_revision_and_plan_files_nothing(self):
        self.file_stay("Orchard House", "1982-06", "1986-06")
        proposal = lo.propose(LETTER, self.root, call=ScriptedCall(reading=reading(units=[
            read_unit("u1", "residences", "Orchard House", LETTER,
                      record={"label": "Orchard House", "city": "Orchard City"},
                      dates=read_dates("1982-08", "1986-06"))])), now=NOW,
            evidence="relative", evidence_source="witness:dad")
        runner = FakeRunner(self.root, ready=True, proposal=proposal)
        record, finished = self.start(runner, yes=True, no_push=True)
        self.assertTrue(finished)
        self.assertEqual(record["phases"]["asking"]["mode"], "yes")
        self.assertEqual(record["phases"]["asking"]["decided"], [])
        self.assertEqual(record["phases"]["landmarks"]["status"], "skipped")
        self.assertFalse(any("--apply" in c for c in runner.calls))

        self.lines.clear()
        runner2 = FakeRunner(self.root, ready=True, proposal=proposal)
        record2, finished2 = self.start(runner2, plan=True)
        self.assertTrue(finished2)
        self.assertFalse(any(c[0] == "ingest-story" for c in runner2.calls))
        self.assertFalse(any("--apply" in c for c in runner2.calls))
        self.assertFalse(any(c[0] in ("classify-story", "compile") for c in runner2.calls))
        self.assertEqual(runner2.git_calls[0][0], "pull")
        self.assertFalse(any(c[0] in ("commit", "push") for c in runner2.git_calls))
        self.assertIn("[revision]", "\n".join(self.lines))
        self.assertIn("intake: plan done (nothing filed)", "\n".join(self.lines))

    def test_a_ready_provider_runs_the_whole_way_and_pushes_with_one_retry(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=True, proposal=proposal)
        runner.push_fail_times = 1
        record, finished = self.start(runner, yes=True)
        self.assertTrue(finished)
        self.assertEqual(len(runner.ai_calls), 2)  # reading + classification
        self.assertEqual(record["phases"]["pushing"]["pushed"], True)
        pushes = [c for c in runner.git_calls if c[0] == "push"]
        self.assertEqual(len(pushes), 2)
        self.assertIn(["pull", "--rebase", "--autostash"], runner.git_calls[1:])
        self.assertIn(intake.CONVERGES_LINE, "\n".join(self.lines))
        self.assertEqual(runner.locks, 1)  # the commit, and only the commit, holds the lease
        self.assertEqual(record["phases"]["landmarks"]["new"], 1)
        # A record intake carries --record through to ingest-story.
        runner3 = FakeRunner(self.root, ready=True, proposal=proposal)
        record3, _ = self.start(runner3, kind="record", witness=None,
                                record_ref="letters:itinerary", yes=True, no_push=True)
        filing = next(c for c in runner3.calls if c[0] == "ingest-story")
        self.assertEqual(filing[filing.index("--record") + 1], "letters:itinerary")
        self.assertEqual(record3["evidence"], "document")

    def test_a_ready_provider_drafts_only_the_scoped_pages_then_compiles_without_a_model(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=True, proposal=proposal)
        synth = self.root / "state" / "synthesis"
        runner.emitted_tasks = [
            {"slug": f"p{i}", "title": f"P{i}", "type": "person",
             "narrative_path": str(synth / f"p{i}.md"),
             "sources": [{"id": "manual:2026-10-06-test",
                          "source": "sources/manual/2026-10-06-test.md", "body": "b"}]}
            for i in range(4)] + [
            {"slug": "other", "narrative_path": str(synth / "other.md"),
             "sources": [{"id": "answer:A1", "source": "answers/A1.md"}]}]
        record, finished = self.start(runner, yes=True, no_push=True, cap=2)
        self.assertTrue(finished)
        self.assertEqual(record["phases"]["compiling"]["pages"], ["p0", "p1"])
        drafts = [c for c in runner.ai_calls if c.startswith("Write the wiki page narrative")]
        self.assertEqual(len(drafts), 2)
        self.assertTrue((synth / "p0.md").is_file() and (synth / "p1.md").is_file())
        self.assertFalse((synth / "p2.md").exists() or (synth / "other.md").exists())
        compiles = [c for c in runner.calls if c[0] == "compile"]
        self.assertEqual(compiles[-1], ["compile", "--no-ai"])
        self.assertNotIn(["compile"], compiles)

    def test_a_timed_out_wait_is_not_a_failed_job_poll_until_terminal(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=True, proposal=proposal)
        runner.compile_wait_times_out = True
        runner.job_states = [{"state": "running"}, {"state": "running"},
                             {"state": "succeeded", "exit_code": 0}]
        record, finished = self.start(runner, yes=True, no_push=True)
        self.assertTrue(finished)
        self.assertEqual(record["phases"]["compiling"]["status"], "done")
        self.assertEqual(runner.slept, 2 * intake.JOB_POLL_SECONDS)
        self.assertIn("intake: compile job j123 still running — waiting for it", self.lines)

    def test_a_failed_job_says_why_with_stderr(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=True, proposal=proposal)
        runner.compile_wait_times_out = True
        runner.job_states = [{"state": "failed", "exit_code": 2, "failure_code": "command_failed"}]
        with self.assertRaises(intake.IntakeError) as caught:
            self.start(runner, yes=True, no_push=True)
        detail = str(caught.exception)
        self.assertIn("could not complete (timed out)", detail)
        self.assertIn("job j123 failed (command_failed)", detail)
        self.assertIn("Queued compile job j123", detail)
        self.assertEqual(intake._detail(intake.Result(1)), "exit 1, no output")

    def test_the_report_never_claims_a_commit_that_did_not_happen(self):
        record = {"phases": {"pushing": {"status": "done", "committed": False, "pushed": False},
                             "compiling": {"status": "done"}}}
        self.assertIn("loop       compiled · nothing to commit", intake.render_report(record))
        record["phases"]["pushing"]["committed"] = True
        self.assertIn("compiled · committed", intake.render_report(record))

    def test_intake_is_an_orchestrator_that_never_holds_the_lease_whole(self):
        import lifehug
        self.assertIn("intake", lifehug.READ_ONLY_COMMANDS)
        self.assertNotIn("intake", lifehug.DIRECT_MUTATION_COMMANDS)

    def test_a_draft_another_compile_consumed_is_not_still_needed(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=False, proposal=proposal)
        synth = self.root / "state" / "synthesis"
        runner.emitted_tasks = [
            {"slug": "dad", "narrative_path": str(synth / "dad.md"),
             "sources": [{"id": "manual:2026-10-06-test", "source": "sources/manual/2026-10-06-test.md"}]}]
        record, _ = self.start(runner, no_push=True, yes=True)
        folder = intake.intake_dir(self.root, record["id"])
        (folder / "reading.completion.json").write_text("{}", encoding="utf-8")
        step = intake.Intake(self.root, intake.load_intake(self.root, record["id"]), runner=runner, say=self.say)
        step.run(completions=folder / "reading.completion.json")
        (folder / "classify.response.json").write_text("{}", encoding="utf-8")
        step = intake.Intake(self.root, intake.load_intake(self.root, record["id"]), runner=runner, say=self.say)
        self.assertFalse(step.run(response=folder / "classify.response.json"))
        self.assertEqual(step.record["phases"]["compiling"]["status"], "waiting")
        # A sibling's compile consumed the draft: no file, and no longer uncached.
        runner.emitted_tasks = []
        self.lines.clear()
        final = intake.Intake(self.root, intake.load_intake(self.root, record["id"]), runner=runner, say=self.say)
        self.assertTrue(final.run())
        self.assertFalse(any("still needs" in line for line in self.lines))

    def test_a_terminal_ask_decides_card_by_card(self):
        proposal = self.real_proposal()
        runner = FakeRunner(self.root, ready=True, proposal=proposal)
        asked: list[str] = []

        def ask(card):
            asked.append(card["kind"])
            return False

        record, finished = self.start(runner, ask=ask, no_push=True)
        self.assertTrue(finished)
        self.assertEqual(asked, ["new"])  # the duplicate is never asked
        self.assertEqual(record["phases"]["asking"]["mode"], "terminal")
        self.assertEqual(record["phases"]["landmarks"]["status"], "skipped")


class RecordAndCliTests(IntakeCase):
    def test_the_record_is_durable_and_listed(self):
        runner = FakeRunner(self.root, ready=False, proposal=None)
        record, finished = self.start(runner, no_serve=True)
        self.assertFalse(finished)
        loaded = intake.load_intake(self.root, record["id"])
        self.assertEqual(loaded["text_sha256"], record["text_sha256"])
        self.assertEqual((intake.intake_dir(self.root, record["id"]) / "text.md").read_text().strip(), LETTER)
        rows = intake.list_intakes(self.root)
        self.assertEqual([r["id"] for r in rows], [record["id"]])
        with self.assertRaises(intake.IntakeError):
            intake.load_intake(self.root, "in-nope")

    def test_the_outer_door_hands_argv_through(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        args = parser.parse_args(["intake", "start", "--witness", "Dad", "--plan"])
        self.assertEqual(args.intake_args, ["start", "--witness", "Dad", "--plan"])
        self.assertIs(args.func, lifehug.cmd_intake)
        inner = intake.build_parser()
        parsed = inner.parse_args(["start", "--record", "letters:x", "--evidence", "document",
                                   "--yes", "--no-push"])
        self.assertEqual(parsed.record, "letters:x")
        self.assertTrue(parsed.yes)
        cont = inner.parse_args(["continue", "in-1", "--units", "a,b"])
        self.assertEqual(cont.units, "a,b")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            inner.parse_args(["start", "--story", "--witness", "Mom"])

    def test_every_new_file_ships_in_framework_files(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        shipped = set(manifest["framework_files"])
        for name in ("system/intake.py", "skills/intake/SKILL.md", "tests/test_intake.py"):
            self.assertIn(name, shipped)
        self.assertGreaterEqual(int(manifest["version"]), 398)

    def test_ingest_story_files_a_third_party_record(self):
        import argparse  # noqa: PLC0415

        import ingest_story  # noqa: PLC0415

        args = argparse.Namespace(title="Record — itinerary", source="cli",
                                  captured_at=NOW, sensitivity="private",
                                  witness=None, kind="story",
                                  record="family-letters:dave-mission-2001/travel-itinerary")
        self.assertEqual(ingest_story.content_source_type(args), "external_record")
        text = ingest_story.frontmatter(args, "sources/manual/x.md", [], "# x\n\nbody\n")
        self.assertIn('type: "external_record"', text)
        self.assertIn('source_trust: "external_record"', text)
        self.assertIn('authority: "third_party_record"', text)
        self.assertIn('record_ref: "family-letters:dave-mission-2001/travel-itinerary"', text)
        plain = argparse.Namespace(title="t", source="cli", captured_at=NOW, sensitivity="private",
                                   witness=None, kind="story", record=None)
        self.assertEqual(ingest_story.content_source_type(plain), "unprompted_story")
        self.assertNotIn("authority", ingest_story.frontmatter(plain, "sources/manual/y.md", [], "b"))


if __name__ == "__main__":
    unittest.main()
