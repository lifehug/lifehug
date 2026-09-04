"""The host-run READING protocol for Add Landmark (`offer` mode).

Controlling design: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` — R3 (the
submitted text is durable on submit, whatever became of the reading) — and
that program's `add-landmark-reading-plan.md` §2 (R6, R9). ADR 0033's Cut 6c
amendment as rewritten by Cut 6f: three doors became TWO, because three
extraction passes became ONE reading.

WHY this exists as its own file rather than growing `test_landmark_offer.py`:
that file pins `propose`/`apply`/`retract` themselves; this one pins that a
host DRIVING those same passes from another process — asking for the
prompts, making the calls itself, handing the completions back — produces
the byte-identical proposal a package-driven call would have. Same subject,
a different seam.

No live model call anywhere in this file: every completion is either
recorded in `offer_fixtures.json` or scripted here, exactly as
`test_landmark_offer.py` and `landmarks_evals.py` both do it.

Synthetic data only; NEVER references ~/Workspace/dave.
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

import entity_roster  # noqa: E402
import landmark_offer as lo  # noqa: E402
import landmarks_evals as ev  # noqa: E402
import lifehug_core  # noqa: E402
import timeline  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-03T00:00:00Z"


@contextlib.contextmanager
def synthetic_vault(root: Path):
    """The exact wiring `tests/test_landmark_offer.py`'s own fixture uses."""
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
    orig_store = timeline.LANDMARKS_STORE
    orig_entity_dir = entity_roster.ENTITY_DIR
    timeline.LANDMARKS_STORE = root / "state" / "landmarks.json"
    entity_roster.ENTITY_DIR = root / "state" / "entity_rosters"
    try:
        yield root
    finally:
        timeline.LANDMARKS_STORE = orig_store
        entity_roster.ENTITY_DIR = orig_entity_dir


class ScriptedCall:
    """`tests/test_landmark_offer.py`'s own scripted ``call``, reproduced
    here so this file needs nothing from that one (no test imports another).

    One reading per submission (R9), so there is nothing to dispatch on."""

    EMPTY = lo.EMPTY_COMPLETION

    def __init__(self, *, reading: object = None):
        self.reading = reading if reading is not None else self.EMPTY
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model: str) -> str:
        self.prompts.append(prompt)
        return (self.reading if isinstance(self.reading, str)
                else json.dumps(self.reading))


def load_goldens() -> list[dict]:
    return ev.load_offer_fixtures()


def _in_process_replay(fixture: dict) -> tuple[ScriptedCall, dict]:
    """`propose(call=ScriptedCall(...))`, in-process — the baseline every
    host-run step is compared against."""
    call = ScriptedCall(reading=fixture["completions"].get("reading"))
    proposal = lo.propose(fixture["source_text"], None, call=call,
                          write=False, landmarks={}, roster={},
                          generation=0, now=NOW)
    return call, proposal


# --------------------------------------------------------------------------
# The five decision-record §5.6 goldens, both ways
# --------------------------------------------------------------------------


class GoldenReplayTests(unittest.TestCase):
    def test_the_five_examples_are_all_covered(self):
        ids = {fixture["fixture_id"] for fixture in load_goldens()}
        self.assertEqual(ids, set(ev.REQUIRED_OFFER_GOLDEN_IDS))

    def test_step1_reading_prompt_is_the_exact_prompt_call_received(self):
        """Same leaf, same substitutions — asserted by capturing the
        in-process `call`'s own prompt, of which there is exactly one."""
        for fixture in load_goldens():
            with self.subTest(fixture=fixture["fixture_id"]):
                call, proposal = _in_process_replay(fixture)
                self.assertEqual(len(call.prompts), 1)
                step1 = lo.host_reading_prompt(fixture["source_text"], None,
                                               landmarks={}, roster={})
                self.assertEqual(step1["reading"]["prompt"], call.prompts[0])
                self.assertEqual(step1["reading"]["model"],
                                 lo.lr.DEFAULT_READING_ROLE)
                extractor = next(row for row in proposal["extractors"]
                                 if row["name"] == "landmark_reading")
                self.assertEqual(step1["reading"]["prompt_version"],
                                 extractor["prompt_version"])

    def test_the_protocol_has_exactly_two_doors(self):
        """R6 deleted the passes and the protocol shrank with them: there is
        no listener prompt, no recorder prompts, and no way to ask for one."""
        for gone in ("host_listener_prompt", "host_recorder_prompts"):
            self.assertFalse(hasattr(lo, gone), gone)
        self.assertIn("host_reading_prompt", lo.__all__)

    def test_step3_is_byte_identical_to_the_in_process_replay(self):
        """Scope item 4: modulo `created_at`, which is pinned equal here by
        passing the SAME `now` to both roads."""
        for fixture in load_goldens():
            with self.subTest(fixture=fixture["fixture_id"]):
                _call, in_process = _in_process_replay(fixture)
                via_completions = lo.propose_from_completions(
                    fixture["source_text"], None, fixture["completions"],
                    write=False, landmarks={}, roster={}, generation=0,
                    now=NOW)
                self.assertEqual(via_completions, in_process)
                self.assertEqual(via_completions["state"],
                                 fixture["expected"]["state"])

    def test_the_completions_file_accepts_raw_text_or_parsed_objects(self):
        """`offer_fixtures.json` carries a parsed object; a real host's file
        would carry the raw completion string a model returned. Both must
        drive `propose_from_completions` to the same proposal."""
        fixture = next(row for row in load_goldens()
                       if row["fixture_id"] == "offer-free-prose-stay")
        as_objects = lo.propose_from_completions(
            fixture["source_text"], None, fixture["completions"], write=False,
            landmarks={}, roster={}, generation=0, now=NOW)
        via_text = lo.propose_from_completions(
            fixture["source_text"], None,
            {"reading": json.dumps(fixture["completions"]["reading"])},
            write=False, landmarks={}, roster={}, generation=0, now=NOW)
        self.assertEqual(as_objects, via_text)


# --------------------------------------------------------------------------
# A completion a host could not use: still writes, still exits 0 (R3)
# --------------------------------------------------------------------------


class FailedProposalStillWritesTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="offer-host-failed-")
        self._ctx = synthetic_vault(tmp)
        self.root = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def test_an_unusable_reading_completion_still_writes_a_failed_proposal(self):
        text = "I lived in Mesa from 1990 to 1992."
        completions = {"reading": "not JSON at all, just prose."}
        proposal = lo.propose_from_completions(text, self.root, completions,
                                               now=NOW)
        self.assertEqual(proposal["state"], "failed")
        self.assertIsInstance(proposal["failure"], dict)
        self.assertIn(proposal["failure"]["class"], lo.FAILURE_CLASSES)
        # R3: the submitted text is durable regardless.
        self.assertEqual(proposal["source_text"], text)
        path = lo.proposal_path(self.root, proposal["proposal_id"])
        self.assertTrue(path.is_file())
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["state"], "failed")
        self.assertEqual(on_disk["source_text"], text)

    def test_the_cli_exits_0_on_a_written_failed_proposal(self):
        completions_path = self.root / "completions.json"
        completions_path.write_text(
            json.dumps({"reading": "not JSON at all."}), encoding="utf-8")
        text_path = self.root / "text.txt"
        text_path.write_text("I lived in Mesa from 1990 to 1992.",
                             encoding="utf-8")
        orig_repo_dir = lifehug_core.REPO_DIR
        lifehug_core.REPO_DIR = self.root
        try:
            code = lo.main(["--propose", "--completions", str(completions_path),
                            "--from-file", str(text_path)])
        finally:
            lifehug_core.REPO_DIR = orig_repo_dir
        self.assertEqual(code, 0)
        proposals = list((self.root / "state" / "landmarks" / "offers").glob("*.json"))
        self.assertEqual(len(proposals), 1)
        self.assertEqual(json.loads(proposals[0].read_text())["state"], "failed")

    def test_the_written_proposal_is_byte_stable_across_two_runs(self):
        text = "I lived in Mesa from 1990 to 1992."
        completions = {"reading": "not JSON at all."}
        first = lo.propose_from_completions(text, self.root, completions,
                                            now=NOW)
        path = lo.proposal_path(self.root, first["proposal_id"])
        first_bytes = path.read_bytes()
        second = lo.propose_from_completions(text, self.root, completions,
                                             now=NOW)
        second_bytes = path.read_bytes()
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        self.assertEqual(first_bytes, second_bytes)


# --------------------------------------------------------------------------
# A proposal, filed and written for real (not just replayed pure)
# --------------------------------------------------------------------------


class WrittenProposalTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = root_parent_tmp(self, ROOT, prefix="offer-host-write-")
        self._ctx = synthetic_vault(tmp)
        self.root = self._ctx.__enter__()
        self.addCleanup(self._ctx.__exit__, None, None, None)

    def test_the_cli_road_is_byte_identical_to_the_in_process_one(self):
        """The determinism pin, run through `main` rather than around it:
        `--prompts` prints ONE prompt, `--completions` prints the proposal a
        package-driven `propose(call=ScriptedCall(...))` would have built."""
        fixture = next(row for row in load_goldens()
                       if row["fixture_id"] == "offer-residence-document")
        text_path = self.root / "text.txt"
        text_path.write_text(fixture["source_text"], encoding="utf-8")
        completions_path = self.root / "completions.json"
        completions_path.write_text(json.dumps(fixture["completions"]),
                                    encoding="utf-8")
        orig_repo_dir = lifehug_core.REPO_DIR
        lifehug_core.REPO_DIR = self.root
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = lo.main(["--propose", "--prompts",
                                "--from-file", str(text_path)])
            self.assertEqual(code, 0)
            prompts = json.loads(buffer.getvalue())
            self.assertEqual(list(prompts), ["reading"])

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = lo.main(["--propose", "--completions",
                                str(completions_path),
                                "--from-file", str(text_path)])
            self.assertEqual(code, 0)
            via_cli = json.loads(buffer.getvalue())
        finally:
            lifehug_core.REPO_DIR = orig_repo_dir

        call = ScriptedCall(reading=fixture["completions"]["reading"])
        in_process = lo.propose(fixture["source_text"], self.root, call=call,
                                write=False, now=via_cli["created_at"])
        self.assertEqual(len(call.prompts), 1)
        self.assertEqual(call.prompts[0], prompts["reading"]["prompt"])
        self.assertEqual(via_cli, in_process)

    def test_completions_driven_propose_writes_the_same_file_a_live_call_would(self):
        fixture = next(row for row in load_goldens()
                       if row["fixture_id"] == "offer-free-prose-stay")
        call = ScriptedCall(reading=fixture["completions"]["reading"])
        live = lo.propose(fixture["source_text"], self.root, call=call, now=NOW)
        live_path = lo.proposal_path(self.root, live["proposal_id"])
        live_bytes = live_path.read_text(encoding="utf-8")

        # A second, otherwise-empty vault, driven only through the
        # completions door.
        tmp2 = root_parent_tmp(self, ROOT, prefix="offer-host-write2-")
        with synthetic_vault(tmp2) as root2:
            via_completions = lo.propose_from_completions(
                fixture["source_text"], root2, fixture["completions"], now=NOW)
            via_path = lo.proposal_path(root2, via_completions["proposal_id"])
            via_bytes = via_path.read_text(encoding="utf-8")
        self.assertEqual(live["proposal_id"], via_completions["proposal_id"])
        self.assertEqual(live_bytes, via_bytes)


# --------------------------------------------------------------------------
# The context door — a host's own vault reading, handed over
# --------------------------------------------------------------------------


class ContextTests(unittest.TestCase):
    def test_load_host_context_reads_the_three_keywords(self):
        tmp_dir = root_parent_tmp(self, ROOT, prefix="offer-host-ctx-")
        path = tmp_dir / "context.json"
        path.write_text(json.dumps(
            {"landmarks": {"residences": []}, "roster": {}, "generation": 3}),
            encoding="utf-8")
        context = lo.load_host_context(path)
        self.assertEqual(context["landmarks"], {"residences": []})
        self.assertEqual(context["generation"], 3)

    def test_an_unreadable_context_file_raises_unsupported_input(self):
        tmp_dir = root_parent_tmp(self, ROOT, prefix="offer-host-ctx2-")
        path = tmp_dir / "missing.json"
        with self.assertRaises(lo.LandmarkOfferError) as caught:
            lo.load_host_context(path)
        self.assertEqual(caught.exception.code, "unsupported_input")

    def test_prompts_are_pure_over_a_supplied_context_with_no_vault(self):
        """Supplying `landmarks` and `roster` skips reading a vault at all —
        the whole point of `--context`."""
        step1 = lo.host_reading_prompt(
            "I lived in Mesa from 1990 to 1992.", "/nonexistent/not-a-vault",
            landmarks={"residences": [{"label": "Tempe", "city": "Tempe"}]},
            roster={})
        self.assertIn("Tempe", step1["reading"]["prompt"])


# --------------------------------------------------------------------------
# Wiring: the new flags exist on the outer CLI too
# --------------------------------------------------------------------------


class WiringTests(unittest.TestCase):
    def test_the_outer_cli_carries_the_host_run_flags(self):
        import lifehug  # noqa: PLC0415

        parser = lifehug.build_parser()
        offer = next(action.choices["landmark-offer"]
                    for action in parser._subparsers._group_actions  # noqa: SLF001
                    if "landmark-offer" in getattr(action, "choices", ()))
        dests = {action.dest for action in offer._actions}  # noqa: SLF001
        for flag in ("prompts", "context", "completions"):
            self.assertIn(flag, dests)
        # Cut 6f: the pass it named is gone, so the flag is gone with it.
        self.assertNotIn("listener_completion", dests)

    def test_the_new_test_module_ships(self):
        manifest = json.loads((SYSTEM / "version.json").read_text(
            encoding="utf-8"))
        self.assertIn("tests/test_landmark_offer_host.py",
                      manifest["framework_files"])


if __name__ == "__main__":
    unittest.main()
