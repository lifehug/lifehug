#!/usr/bin/env python3
"""Intake — the terminal front door for stories, witnessed material and
landmark revisions (lifehug#469, v398).

A story is the owner talking; intake is *"here is evidence"*. One verb runs
the eight phases that were eight commands — capture, read, ask, file,
classify, compile, push, report — and prints one line per phase so a terminal
and the Claude Code skill that drives it show the same progress:

    intake: filing …
    intake: filing done (sources/manual/2026-10-06-dad-s-letter.md)
    intake: reading …

**It adds no extractor and no second writer.** Capture is `ingest_story.py`;
reading is Add Landmark's host-run protocol (`landmark-offer --propose
--prompts` → one completion → `--completions`, ADR 0033 Cut 6f); filing is
`landmark-offer --apply`, the one road an answered landmark question takes
(R3a), interval-aware so two stays at one address stay two; classification is
`classify-story --prompt` / `--from-response`; the wiki is `compile`. Every
model step has a keyless door, and intake is a STATE MACHINE over them: with a
ready provider (`ai-status` exit 0) it runs the whole way; keyless, it stops at
each model step, prints what the agent must write and where, and `intake
continue <id>` picks the phases up again. Nothing is lost between stops —
`state/intake/<id>/intake.json` is the durable record of where an intake is.

**A revision or a conflict is never filed without the owner's yes**, even
under `--yes`. `--yes` files only units the ask would have shown as NEW:
nothing already filed, nothing overlapping, nothing revising (v397's
`revises`). `--plan` reads and asks and files nothing beyond the durable
proposal.

Phases, in order:

    preflight   pull --rebase --autostash (non-fatal); ai-status; viewer probe
    filing      ingest-story (--story | --witness NAME | --record REF)
    reading     landmark-offer --propose --prompts → completion → --completions
    asking      one card per unit: new / revision / conflict; duplicates one line
    landmarks   landmark-offer --apply <proposal> --units <confirmed>
    classifying classify-story --prompt → response → --from-response
    compiling   compile --emit-tasks (scoped to this source, capped) → drafts →
                compile --no-ai (model-free; the rest wait for the next compile)
    pushing     commit tracked vault paths; push with one rebase retry
    report      links, receipt, undo

Pure where it can be: the cards (:func:`cards_from_proposal`), the decision
policy (:func:`decide_units`), the task scoping (:func:`scope_tasks`) and the
report (:func:`render_report`) take data and return data; the phase runner
takes an injected :class:`Runner` so tests script every subprocess.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lifehug_core import REPO_DIR, now_utc

SYSTEM_DIR = Path(__file__).resolve().parent

#: Where an intake keeps its record and its hand-offs. Gitignored: this is
#: local orchestration state, like `state/jobs/` and `state/agent_tasks/`.
INTAKE_DIR_NAME = "intake"

PHASES = ("preflight", "filing", "reading", "asking", "landmarks",
          "classifying", "compiling", "pushing", "report")

KINDS = ("story", "witness", "record")
EVIDENCE_BASES = ("relative", "document")

#: The four things a card can be. `duplicate` collapses to one summary line;
#: the other three are asked, in text order.
CARD_KINDS = ("new", "revision", "conflict", "duplicate")

#: How many pages one intake may ask the agent to synthesize. The rest keep
#: their prior prose (compile never downgrades a synthesized page) until the
#: next compile — one story must never trigger fifty drafts.
DEFAULT_SYNTHESIS_CAP = 6

DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 8765

PUSH_ATTEMPTS = 2

#: A queued mutation (`compile` runs through the durable jobs worker) can
#: outlive `_queue_and_wait`'s fixed wait while the job is still healthy.
#: Intake then polls `jobs.py show <id>` until the job is terminal, saying
#: so once a minute, up to this ceiling — a timed-out WAIT is not a failed JOB.
JOB_POLL_SECONDS = 5.0
JOB_POLL_SAY_EVERY = 12
JOB_POLL_CEILING_SECONDS = 3 * 60 * 60
JOB_TERMINAL_STATES = ("succeeded", "failed")
QUEUED_JOB_RE = re.compile(r"Queued (\S+) job (\S+)")

#: The phase line shape, named so the skill and the tests read one definition.
PHASE_PREFIX = "intake:"

#: What `pushing` says when the push landed: Lifehug Cloud clones HEAD at its
#: next touch (platform ADR 0011); nothing here waits for it.
CONVERGES_LINE = "Lifehug Cloud will see this at its next touch."


class IntakeError(Exception):
    """A typed intake failure. ``code`` is one of a small fixed set."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


# --------------------------------------------------------------------------
# Running things (injected, so tests script every subprocess)
# --------------------------------------------------------------------------

@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner:
    """Runs one subprocess in the vault. Replace in tests."""

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root)

    def lifehug(self, *args: str, stdin: str | None = None) -> Result:
        return self.run([sys.executable, str(SYSTEM_DIR / "lifehug.py"), *args],
                        stdin=stdin)

    def git(self, *args: str) -> Result:
        return self.run(["git", "-C", str(self.vault_root), *args])

    def run(self, argv: list[str], *, stdin: str | None = None) -> Result:
        done = subprocess.run(argv, cwd=self.vault_root, input=stdin,
                              capture_output=True, text=True)
        return Result(done.returncode, done.stdout or "", done.stderr or "")

    def port_open(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    def spawn_viewer(self, host: str, port: int) -> None:
        subprocess.Popen(  # noqa: S603 — the vault's own viewer, detached
            [sys.executable, str(SYSTEM_DIR / "lifehug.py"), "serve",
             "--host", host, "--port", str(port)],
            cwd=self.vault_root, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
            # The viewer outlives this intake: it never inherits a writer token.
            env={k: v for k, v in os.environ.items() if k != "LIFEHUG_JOB_RUNNER_TOKEN"})

    def writer_lock(self):
        """The kernel writer lease, for the one step intake writes the vault
        itself (the commit). Re-entrant by token: under a live lease (a job
        worker running intake) it is a no-op."""
        import contextlib  # noqa: PLC0415

        import jobs  # noqa: PLC0415

        if jobs.writer_token_is_live(os.environ.get("LIFEHUG_JOB_RUNNER_TOKEN"),
                                     vault_root=self.vault_root):
            return contextlib.nullcontext()
        return jobs.writer_session(self.vault_root)

    def job_state(self, job_id: str) -> dict:
        """``jobs.py show <id>`` as data (``{}`` when it cannot be read)."""
        done = self.run([sys.executable, str(SYSTEM_DIR / "jobs.py"), "show", job_id])
        try:
            return json.loads(done.stdout) if done.returncode == 0 else {}
        except ValueError:
            return {}

    def sleep(self, seconds: float) -> None:
        import time  # noqa: PLC0415

        time.sleep(seconds)

    def call_ai(self, prompt: str, model: str | None) -> str:
        from ai_provider import call_ai  # noqa: PLC0415

        return call_ai(prompt, model or "")

    def provider_ready(self) -> tuple[bool, str]:
        from ai_provider import provider_status  # noqa: PLC0415

        status = provider_status(probe=True)
        return bool(status.ready), str(status.model)


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------

def intake_dir(vault_root: Path, intake_id: str) -> Path:
    return Path(vault_root) / "state" / INTAKE_DIR_NAME / intake_id


def new_intake_id(now: str) -> str:
    stamp = re.sub(r"[^0-9]", "", now)[:14]
    return f"in-{stamp}-{secrets.token_hex(3)}"


def load_intake(vault_root: Path, intake_id: str) -> dict:
    path = intake_dir(vault_root, intake_id) / "intake.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IntakeError("unknown_intake", f"no intake {intake_id}: {exc}") from exc


def _write_vault_text(vault_root: Path, path: Path, content: str) -> Path:
    """Every intake write goes through the no-follow vault authority."""
    from vault_paths import atomic_write_vault_text, ensure_vault_directory  # noqa: PLC0415

    ensure_vault_directory(Path(path).parent, vault_root=vault_root)
    atomic_write_vault_text(path, content, vault_root=vault_root)
    return Path(path)


def save_intake(vault_root: Path, record: dict) -> Path:
    path = intake_dir(vault_root, record["id"]) / "intake.json"
    return _write_vault_text(vault_root, path,
                             json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def list_intakes(vault_root: Path) -> list[dict]:
    base = Path(vault_root) / "state" / INTAKE_DIR_NAME
    rows = []
    if not base.is_dir():
        return rows
    for folder in sorted(base.iterdir()):
        path = folder / "intake.json"
        if path.is_file():
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return rows


def new_record(*, kind: str, text: str, title: str | None, witness: str | None,
               record_ref: str | None, evidence: str | None,
               evidence_source: str | None, source_label: str, plan: bool,
               yes: bool, no_serve: bool, no_push: bool, cap: int,
               now: str | None = None, sensitivity: str | None = None,
               read: bool = True, updates_file: str | None = None,
               update_kind: str | None = None) -> dict:
    if kind not in KINDS:
        raise IntakeError("unsupported_input", f"kind must be one of {KINDS}")
    if not text.strip():
        raise IntakeError("unsupported_input", "intake needs some text")
    if kind == "witness" and not (witness or "").strip():
        raise IntakeError("unsupported_input", "--witness needs a name")
    if kind == "record" and not (record_ref or "").strip():
        raise IntakeError("unsupported_input", "--record needs a reference")
    if evidence and evidence not in EVIDENCE_BASES:
        raise IntakeError("unsupported_input",
                          f"--evidence must be one of {EVIDENCE_BASES}")
    if kind == "story" and evidence:
        raise IntakeError("unsupported_input",
                          "--evidence is for --witness or --record; a story is "
                          "the person's own words")
    # A witness is relative evidence by definition; a record defaults to a
    # document's. Both can be said explicitly; neither can be contradicted.
    if kind == "witness":
        evidence = "relative"
        evidence_source = evidence_source or f"witness:{_slug(witness or '')}"
    elif kind == "record":
        evidence = evidence or "document"
        evidence_source = evidence_source or (record_ref or "").strip()
    stamp = now or now_utc()
    return {
        "id": new_intake_id(stamp),
        "schema_version": 1,
        "created_at": stamp,
        "kind": kind,
        "title": (title or "").strip() or None,
        "witness": (witness or "").strip() or None,
        "record_ref": (record_ref or "").strip() or None,
        "evidence": evidence,
        "evidence_source": evidence_source,
        "source_label": source_label,
        "plan": bool(plan),
        "yes": bool(yes),
        "no_serve": bool(no_serve),
        "no_push": bool(no_push),
        "synthesis_cap": int(cap),
        # v399 (--from-updates): the filed source's sensitivity, whether the
        # landmark reading runs at all (`kind: record` files skip it), and
        # the update file this intake came from.
        "sensitivity": (sensitivity or "").strip() or None,
        "read": bool(read),
        "updates_file": updates_file,
        "update_kind": update_kind,
        # A batch file with a revision or conflict on it is not finished by
        # `--yes` (which would file its new units and move the file to
        # applied/ with the revision unasked): it waits for the owner.
        "hold_revisions": bool(updates_file),
        "text_sha256": _sha256(text),
        "phases": {name: {"status": "pending"} for name in PHASES},
        "done": False,
    }


def _slug(value: str) -> str:
    from lifehug_core import slugify  # noqa: PLC0415

    return slugify(value)


def _sha256(text: str) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Pure parts: cards, decisions, scoping, report
# --------------------------------------------------------------------------

def card_kind(unit: dict) -> str:
    """Which of :data:`CARD_KINDS` one proposal unit is.

    Conflicts outrank revisions outrank duplicates: a unit that both revises
    a stay and overlaps another identity is shown as the conflict it is.
    """
    if unit.get("conflicts"):
        return "conflict"
    if unit.get("revises"):
        return "revision"
    if unit.get("duplicates"):
        return "duplicate"
    return "new"


def cards_from_proposal(proposal: dict) -> list[dict]:
    """One card per proposal unit, in text order, each saying what it is."""
    import landmark_offer as lo  # noqa: PLC0415

    cards = []
    for unit in proposal.get("units") or ():
        if not isinstance(unit, dict) or not unit.get("unit_id"):
            continue
        kind = card_kind(unit)
        dates = unit.get("dates") or {}
        lines = [lo.render_unit(unit)]
        cards.append({
            "unit_id": unit["unit_id"],
            "kind": kind,
            "domain": unit.get("domain"),
            "subject": unit.get("subject"),
            "start": dates.get("start"),
            "end": dates.get("end"),
            "basis": dates.get("basis"),
            "revises": list(unit.get("revises") or ()),
            "conflicts": list(unit.get("conflicts") or ()),
            "duplicates": list(unit.get("duplicates") or ()),
            "text": "\n".join(lines),
        })
    return cards


def card_counts(cards: list[dict]) -> dict:
    counts = {kind: 0 for kind in CARD_KINDS}
    for card in cards:
        counts[card["kind"]] = counts.get(card["kind"], 0) + 1
    return counts


def decide_units(cards: list[dict], *, yes: bool = False,
                 units: list[str] | None = None, all_new: bool = False,
                 none: bool = False) -> list[str]:
    """Which units to file. The doctrine lives here and nowhere else:

    * an explicit ``units`` list files exactly those (a person named them —
      revisions and conflicts included, that is the yes);
    * ``yes`` or ``all_new`` files every NEW card and nothing else — never a
      revision, never a conflict, never a duplicate;
    * ``none`` files nothing.
    """
    if none:
        return []
    known = {card["unit_id"]: card for card in cards}
    if units:
        unknown = [u for u in units if u not in known]
        if unknown:
            raise IntakeError("unsupported_input",
                              f"no such unit(s): {', '.join(sorted(unknown))}")
        return list(dict.fromkeys(units))
    if yes or all_new:
        return [card["unit_id"] for card in cards if card["kind"] == "new"]
    return []


def scope_tasks(tasks: list[dict], *, source_path: str | None,
                source_id: str | None, cap: int) -> list[dict]:
    """The synthesis tasks that cite THIS intake's source, capped.

    A task cites the source when any of its ``sources[]`` rows names the
    filed path or id. Pages the source did not touch keep their prior prose.
    """
    wanted = []
    for task in tasks:
        rows = task.get("sources") or ()
        hit = any(
            isinstance(row, dict) and (
                (source_path and row.get("source") == source_path)
                or (source_id and row.get("id") == source_id))
            for row in rows)
        if hit:
            wanted.append(task)
    return wanted[: max(0, int(cap))]


def viewer_base(record: dict) -> str:
    pre = (record.get("phases") or {}).get("preflight") or {}
    return str(pre.get("viewer_url") or f"http://{DEFAULT_VIEWER_HOST}:{DEFAULT_VIEWER_PORT}")


def render_report(record: dict) -> str:
    """The closing block: what was filed, where to look, how to undo."""
    from urllib.parse import quote  # noqa: PLC0415

    phases = record.get("phases") or {}
    base = viewer_base(record)
    filing = phases.get("filing") or {}
    asking = phases.get("asking") or {}
    landmarks = phases.get("landmarks") or {}
    classifying = phases.get("classifying") or {}
    compiling = phases.get("compiling") or {}
    pushing = phases.get("pushing") or {}
    counts = asking.get("counts") or {}
    lines = [f"{PHASE_PREFIX} done" if not record.get("plan") else f"{PHASE_PREFIX} plan done (nothing filed)"]
    source = filing.get("source_path")
    if source:
        lines.append(f"  source     {source}   {base}/source-actions?ref={quote(source)}")
    filed = landmarks.get("filed_units") or []
    summary = (f"{landmarks.get('revised', 0)} revised, {landmarks.get('new', 0)} new"
               if filed else "none filed")
    dupes = counts.get("duplicate", 0)
    if dupes:
        summary += f", {dupes} already known"
    receipt = landmarks.get("receipt_id")
    if receipt:
        summary += (f"      receipt {receipt}  undo: python3 system/lifehug.py "
                    f"landmark-offer --retract {receipt}")
    elif counts:
        summary += (f"      cards: {counts.get('new', 0)} new · "
                    f"{counts.get('revision', 0)} revision · "
                    f"{counts.get('conflict', 0)} conflict")
    lines.append(f"  landmarks  {summary}")
    lines.append(f"  timeline   {base}/views/timeline")
    pages = compiling.get("pages") or []
    if pages:
        lines.append(f"  wiki       {' · '.join(pages)}")
    loop = []
    if classifying.get("status") == "done":
        loop.append("classified")
    if compiling.get("status") == "done":
        loop.append("compiled")
    if pushing.get("status") == "done":
        loop.append("pushed" if pushing.get("pushed")
                    else "committed" if pushing.get("committed") else "nothing to commit")
    if loop:
        tail = " · ".join(loop)
        if pushing.get("pushed"):
            tail += f" ({CONVERGES_LINE})"
        lines.append(f"  loop       {tail}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The phase runner
# --------------------------------------------------------------------------

class Intake:
    """One intake, driven phase by phase. ``say`` is where phase lines go."""

    def __init__(self, vault_root: Path, record: dict, *, runner: Runner | None = None,
                 say=print, ask=None) -> None:
        self.root = Path(vault_root)
        self.record = record
        self.runner = runner or Runner(self.root)
        self.say = say
        # ``ask(card) -> bool`` for a terminal; None means "stop and wait".
        self.ask = ask
        self.folder = intake_dir(self.root, record["id"])

    # -- helpers ------------------------------------------------------------

    def phase(self, name: str) -> dict:
        return self.record["phases"].setdefault(name, {"status": "pending"})

    def begin(self, name: str) -> None:
        self.say(f"{PHASE_PREFIX} {name} …")

    def finish(self, name: str, detail: str = "", **fields: object) -> None:
        row = self.phase(name)
        row.update(fields)
        row["status"] = "done"
        row["finished_at"] = now_utc()
        self.save()
        self.say(f"{PHASE_PREFIX} {name} done" + (f" ({detail})" if detail else ""))

    def wait(self, name: str, need: str, *, path: Path | None, next_flags: str) -> None:
        row = self.phase(name)
        row["status"] = "waiting"
        row["waiting_for"] = need
        if path is not None:
            row["waiting_path"] = str(path)
        self.save()
        where = f" — {path}" if path is not None else ""
        self.say(f"{PHASE_PREFIX} {name} needs {need}{where}")
        self.say(f"next: python3 system/lifehug.py intake continue {self.record['id']} {next_flags}".rstrip())

    def save(self) -> None:
        save_intake(self.root, self.record)

    def text(self) -> str:
        return (self.folder / "text.md").read_text(encoding="utf-8")

    def write(self, name: str, content: str) -> Path:
        return _write_vault_text(self.root, self.folder / name, content)

    def _lifehug(self, *args: str, stdin: str | None = None) -> Result:
        return self.runner.lifehug(*args, stdin=stdin)

    def _lifehug_job(self, *args: str) -> Result:
        """Run a queued lifehug command and return the JOB's truth.

        `_queue_and_wait` returns 1 both when the job failed and when its
        fixed wait ran out on a job that is still running. The second is not
        a failure: poll the job by id until it is terminal.
        """
        result = self._lifehug(*args)
        if result.returncode == 0:
            return result
        match = QUEUED_JOB_RE.search(result.stdout or "")
        if not match:
            return result
        job_id = match.group(2)
        waited, polls = 0.0, 0
        while waited < JOB_POLL_CEILING_SECONDS:
            job = self.runner.job_state(job_id)
            state = job.get("state")
            if state in JOB_TERMINAL_STATES:
                if state == "succeeded":
                    return Result(0, (result.stdout or "") + f"\n✓ {match.group(1)} job succeeded\n",
                                  result.stderr)
                return Result(int(job.get("exit_code") or 1), result.stdout,
                              (result.stderr or "")
                              + f"\njob {job_id} failed ({job.get('failure_code', 'command_failed')})")
            if not job:
                break
            if polls % JOB_POLL_SAY_EVERY == 0:
                self.say(f"{PHASE_PREFIX} {args[0]} job {job_id} still {state or 'pending'} — waiting for it")
            polls += 1
            self.runner.sleep(JOB_POLL_SECONDS)
            waited += JOB_POLL_SECONDS
        return result

    @staticmethod
    def _json_from(stdout: str) -> dict:
        """The one JSON object a lifehug.py command printed, whatever the
        worker printed around it (``Queued … job`` lines and the like)."""
        text = stdout.strip()
        try:
            return json.loads(text)
        except ValueError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
        raise IntakeError("write_failure", f"no JSON in command output: {text[:200]!r}")

    # -- drive --------------------------------------------------------------

    def run(self, *, completions: Path | None = None, response: Path | None = None,
            units: list[str] | None = None, all_new: bool = False,
            none: bool = False) -> bool:
        """Advance through every phase that can advance. Returns True when the
        intake is finished (done or planned), False when it is waiting."""
        inputs = {"completions": completions, "response": response,
                  "units": units, "all_new": all_new, "none": none}
        for name in PHASES:
            row = self.phase(name)
            if row.get("status") == "done":
                continue
            if row.get("status") == "skipped":
                continue
            handler = getattr(self, f"phase_{name}")
            accepted = inspect.signature(handler).parameters
            outcome = handler(**{k: v for k, v in inputs.items() if k in accepted})
            if outcome == "waiting":
                return False
        self.record["done"] = True
        self.save()
        self.say(render_report(self.record))
        return True

    # -- phases -------------------------------------------------------------

    def phase_preflight(self) -> str:
        self.begin("preflight")
        pulled = self.runner.git("pull", "--rebase", "--autostash")
        pull_note = "pulled" if pulled.returncode == 0 else "pull skipped"
        ready, model = self.runner.provider_ready()
        host, port = DEFAULT_VIEWER_HOST, DEFAULT_VIEWER_PORT
        viewer = "viewer running"
        if not self.runner.port_open(host, port):
            if self.record.get("no_serve") or self.record.get("plan"):
                viewer = "viewer not running"
            else:
                self.runner.spawn_viewer(host, port)
                viewer = "viewer started"
        self.finish("preflight",
                    f"{pull_note} · {'provider ready' if ready else 'keyless'} · {viewer}",
                    pull=pulled.returncode == 0, provider_ready=ready,
                    model=model, viewer_url=f"http://{host}:{port}")
        return "done"

    def phase_filing(self) -> str:
        self.begin("filing")
        record = self.record
        text = self.text()
        if record.get("plan"):
            self.finish("filing", "plan: nothing written", source_path=None,
                        source_id=None)
            return "done"
        args = ["ingest-story", "--source", record["source_label"]]
        if record.get("title"):
            args += ["--title", record["title"]]
        if record["kind"] == "witness":
            args += ["--witness", record["witness"]]
        elif record["kind"] == "record":
            args += ["--record", record["record_ref"]]
        if record.get("sensitivity"):
            args += ["--sensitivity", record["sensitivity"]]
        result = self._lifehug(*args, stdin=text)
        if result.returncode != 0:
            raise IntakeError("write_failure",
                              f"ingest-story failed: {_detail(result)}")
        match = re.search(r":\s+(sources/[^\s]+\.md)\s*$", result.stdout, re.M)
        if not match:
            raise IntakeError("write_failure",
                              f"ingest-story did not name the filed source: {result.stdout.strip()[:200]!r}")
        source_path = match.group(1)
        source_id = f"manual:{Path(source_path).stem}"
        self.finish("filing", source_path, source_path=source_path, source_id=source_id)
        return "done"

    def phase_reading(self, completions: Path | None = None) -> str:
        row = self.phase("reading")
        record = self.record
        if record.get("read") is False:
            for name in ("reading", "asking"):
                self.phase(name).update({"status": "skipped"})
            self.phase("asking")["counts"] = card_counts([])
            self.save()
            self.say(f"{PHASE_PREFIX} reading skipped (a record: filed as a source, not read for landmarks)")
            return "done"
        text_path = self.folder / "text.md"
        evidence_flags: list[str] = []
        if record.get("evidence"):
            evidence_flags += ["--evidence", record["evidence"]]
            if record.get("evidence_source"):
                evidence_flags += ["--evidence-source", record["evidence_source"]]
        if row.get("status") != "waiting":
            self.begin("reading")
            result = self._lifehug("landmark-offer", "--propose", "--prompts",
                                   "--from-file", str(text_path), *evidence_flags)
            if result.returncode != 0:
                raise IntakeError("write_failure",
                                  f"landmark-offer --prompts failed: {_detail(result)}")
            prompt_row = (self._json_from(result.stdout).get("reading") or {})
            prompt_path = self.write("reading.prompt.md", str(prompt_row.get("prompt") or ""))
            row["prompt_path"] = str(prompt_path)
            row["model"] = prompt_row.get("model")
            self.save()
            ready = (self.phase("preflight") or {}).get("provider_ready")
            if ready and completions is None:
                raw = self.runner.call_ai(prompt_path.read_text(encoding="utf-8"),
                                          prompt_row.get("model"))
                completions = self.write("reading.completion.json",
                                         json.dumps({"reading": _parse_completion(raw)},
                                                    ensure_ascii=False))
        if completions is None:
            self.wait("reading", "the reading completion",
                      path=self.folder / "reading.completion.json",
                      next_flags=f"--completions {self.folder / 'reading.completion.json'}")
            return "waiting"
        completions = Path(completions)
        if not completions.is_file():
            raise IntakeError("unsupported_input", f"no completion file: {completions}")
        result = self._lifehug("landmark-offer", "--propose", "--from-file", str(text_path),
                               "--completions", str(completions), *evidence_flags)
        if result.returncode != 0:
            raise IntakeError("write_failure",
                              f"landmark-offer --completions failed: {_detail(result)}")
        proposal = self._json_from(result.stdout)
        self.write("proposal.json", json.dumps(proposal, indent=2, ensure_ascii=False, sort_keys=True))
        state = proposal.get("state")
        units = len(proposal.get("units") or ())
        self.finish("reading", f"{units} unit(s), {state}",
                    proposal_id=proposal.get("proposal_id"), state=state, units=units,
                    failure=proposal.get("failure"))
        return "done"

    def proposal(self) -> dict:
        try:
            return json.loads((self.folder / "proposal.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise IntakeError("write_failure", f"no proposal on this intake: {exc}") from exc

    def phase_asking(self, units: list[str] | None = None, all_new: bool = False,
                     none: bool = False) -> str:
        row = self.phase("asking")
        cards = cards_from_proposal(self.proposal())
        counts = card_counts(cards)
        if row.get("status") != "waiting":
            self.begin("asking")
            row["cards"] = cards
            row["counts"] = counts
            self.save()
            shown = [card for card in cards if card["kind"] != "duplicate"]
            for card in shown:
                self.say(f"[{card['kind']}] {card['unit_id']}")
                self.say(card["text"])
            if counts["duplicate"]:
                self.say(f"({counts['duplicate']} already filed, unchanged — not asked)")
            if not shown:
                self.say("(nothing new to file)")
        if self.record.get("plan"):
            self.finish("asking", _counts_phrase(counts), decided=[], mode="plan")
            return "done"
        chosen: list[str] | None = None
        mode = "explicit"
        if units or all_new or none:
            chosen = decide_units(cards, units=units, all_new=all_new, none=none)
            mode = "units" if units else ("all-new" if all_new else "none")
        elif self.record.get("yes") and not (
                self.record.get("hold_revisions")
                and any(card["kind"] in ("revision", "conflict") for card in cards)):
            chosen = decide_units(cards, yes=True)
            mode = "yes"
        elif not any(card["kind"] != "duplicate" for card in cards):
            chosen, mode = [], "nothing-to-ask"
        elif self.ask is not None:
            chosen = [card["unit_id"] for card in cards
                      if card["kind"] != "duplicate" and self.ask(card)]
            mode = "terminal"
        if chosen is None:
            self.wait("asking", "your decision",
                      path=None,
                      next_flags="--units <id,id> | --all-new | --none")
            return "waiting"
        self.finish("asking", f"{_counts_phrase(counts)}; filing {len(chosen)}",
                    decided=chosen, mode=mode)
        return "done"

    def phase_landmarks(self) -> str:
        asking = self.phase("asking")
        chosen = list(asking.get("decided") or ())
        if self.record.get("plan") or not chosen:
            self.phase("landmarks").update({"status": "skipped", "filed_units": []})
            self.save()
            self.say(f"{PHASE_PREFIX} landmarks skipped (nothing confirmed)")
            return "done"
        self.begin("landmarks")
        proposal_id = (self.phase("reading") or {}).get("proposal_id")
        result = self._lifehug("landmark-offer", "--apply", str(proposal_id),
                               "--units", ",".join(chosen),
                               "--reason", f"intake {self.record['id']}")
        if result.returncode != 0:
            raise IntakeError("write_failure",
                              f"landmark-offer --apply failed: {_detail(result)}")
        receipt = self._json_from(result.stdout)
        by_id = {card["unit_id"]: card for card in asking.get("cards") or ()}
        revised = sum(1 for u in chosen if by_id.get(u, {}).get("kind") == "revision")
        new = sum(1 for u in chosen if by_id.get(u, {}).get("kind") == "new")
        self.finish("landmarks",
                    f"{len(chosen)} filed · receipt {receipt.get('receipt_id')}",
                    receipt_id=receipt.get("receipt_id"), filed_units=chosen,
                    revised=revised, new=new,
                    sentence=receipt.get("sentence"))
        self.say(f"undo: python3 system/lifehug.py landmark-offer --retract {receipt.get('receipt_id')}")
        return "done"

    def phase_classifying(self, response: Path | None = None) -> str:
        row = self.phase("classifying")
        source_path = (self.phase("filing") or {}).get("source_path")
        if self.record.get("plan") or not source_path:
            row.update({"status": "skipped"})
            self.save()
            self.say(f"{PHASE_PREFIX} classifying skipped (plan)")
            return "done"
        if row.get("status") != "waiting":
            self.begin("classifying")
            result = self._lifehug("classify-story", "--prompt", source_path)
            if result.returncode != 0:
                raise IntakeError("write_failure",
                                  f"classify-story --prompt failed: {_detail(result)}")
            if not result.stdout.strip():
                self.finish("classifying", "already current")
                return "done"
            prompt_path = self.write("classify.prompt.md", result.stdout)
            row["prompt_path"] = str(prompt_path)
            self.save()
            ready = (self.phase("preflight") or {}).get("provider_ready")
            if ready and response is None:
                raw = self.runner.call_ai(result.stdout, (self.phase("preflight") or {}).get("model"))
                response = self.write("classify.response.json", raw)
        if response is None:
            self.wait("classifying", "the classification response",
                      path=self.folder / "classify.response.json",
                      next_flags=f"--response {self.folder / 'classify.response.json'}")
            return "waiting"
        response = Path(response)
        if not response.is_file():
            raise IntakeError("unsupported_input", f"no response file: {response}")
        result = self._lifehug("classify-story", "--from-response", str(response),
                               "--source", source_path)
        if result.returncode != 0:
            raise IntakeError("write_failure",
                              f"classify-story --from-response failed: {_detail(result)}")
        self.finish("classifying", "filed", response_path=str(response))
        return "done"

    def phase_compiling(self) -> str:
        """Scoped compile: at most ``synthesis_cap`` pages that cite THIS
        source get fresh prose; everything else keeps its prior prose.

        Both compiles are model-free on purpose. ``compile --emit-tasks``
        lists the pages without cached prose; the scoped ones are drafted
        (by the agent keyless, by the ready provider otherwise) into their
        ``narrative_path``; then ``compile --no-ai`` consumes those drafts and
        renders the rest from cache or preserves them (compile never
        downgrades a synthesized page). A bare ``compile`` would synthesize
        EVERY uncached page through whatever ``wiki_model`` the vault names —
        a cloud call the intake never asked for and the cap exists to stop.
        """
        row = self.phase("compiling")
        filing = self.phase("filing") or {}
        if self.record.get("plan"):
            row.update({"status": "skipped"})
            self.save()
            self.say(f"{PHASE_PREFIX} compiling skipped (plan)")
            return "done"
        ready = (self.phase("preflight") or {}).get("provider_ready")
        if row.get("status") != "waiting":
            self.begin("compiling")
            tasks_path = self.folder / "synthesis.tasks.json"
            result = self._lifehug("compile", "--emit-tasks", str(tasks_path))
            if result.returncode != 0:
                raise IntakeError("write_failure",
                                  f"compile --emit-tasks failed: {_detail(result)}")
            try:
                tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                tasks = []
            scoped = scope_tasks(tasks, source_path=filing.get("source_path"),
                                 source_id=filing.get("source_id"),
                                 cap=int(self.record.get("synthesis_cap") or DEFAULT_SYNTHESIS_CAP))
            scoped_path = self.write("synthesis.scoped.json",
                                     json.dumps(scoped, indent=2, ensure_ascii=False))
            row["tasks"] = [t.get("slug") for t in scoped]
            row["tasks_path"] = str(scoped_path)
            row["uncached"] = len(tasks) if isinstance(tasks, list) else 0
            self.save()
            pending = [t for t in scoped if not Path(t.get("narrative_path") or "").is_file()]
            if pending and ready:
                for task in pending:
                    raw = self.runner.call_ai(synthesis_prompt(task),
                                              (self.phase("preflight") or {}).get("model"))
                    draft = str(raw or "").strip()
                    if draft:
                        _write_vault_text(self.root, Path(task["narrative_path"]), draft + "\n")
                pending = [t for t in scoped if not Path(t.get("narrative_path") or "").is_file()]
            if pending and not ready:
                for task in pending:
                    self.say(f"  draft {task.get('slug')} → {task.get('narrative_path')}")
                self.wait("compiling", f"{len(pending)} page draft(s)",
                          path=scoped_path, next_flags="")
                return "waiting"
        else:
            try:
                scoped_rows = json.loads(Path(row["tasks_path"]).read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                scoped_rows = []
            # A draft another compile already consumed (a sibling intake in
            # the same batch, a manual compile) is no longer a file, and its
            # page is no longer uncached: ask the compiler, not the disk.
            still = self._uncached_slugs()
            pending = [t for t in scoped_rows
                       if t.get("slug") in still
                       and not Path(t.get("narrative_path") or "").is_file()]
            if pending:
                self.say(f"{PHASE_PREFIX} compiling still needs {len(pending)} draft(s); compiling with what is there")
        result = self._lifehug_job("compile", "--no-ai")
        if result.returncode != 0:
            raise IntakeError("write_failure", f"compile failed: {_detail(result)}")
        match = re.search(r"(\d+) page update", result.stdout)
        updates = int(match.group(1)) if match else None
        waiting = max(0, int(row.get("uncached") or 0) - len(row.get("tasks") or ()))
        detail = f"{updates} page update(s)" if updates is not None else "compiled"
        if waiting:
            detail += f"; {waiting} other page(s) wait for the next compile"
        self.finish("compiling", detail,
                    pages=list(row.get("tasks") or []), updates=updates)
        return "done"

    def _uncached_slugs(self) -> set[str]:
        """The slugs `compile --emit-tasks` still lists (pages with no cached
        prose and no draft); empty when the listing cannot be read."""
        tasks_path = self.folder / "synthesis.tasks.json"
        result = self._lifehug("compile", "--emit-tasks", str(tasks_path))
        if result.returncode != 0:
            return set()
        try:
            rows = json.loads(tasks_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {str(t.get("slug")) for t in rows if isinstance(t, dict)}

    def phase_pushing(self) -> str:
        row = self.phase("pushing")
        if self.record.get("plan"):
            row.update({"status": "skipped"})
            self.save()
            self.say(f"{PHASE_PREFIX} pushing skipped (plan)")
            return "done"
        self.begin("pushing")
        paths = [p for p in tracked_paths(self.root) if (self.root / p).exists()]
        committed = False
        pushed = False
        title = self.record.get("title") or (self.phase("filing") or {}).get("source_path") or self.record["id"]
        with self.runner.writer_lock():
            if paths:
                self.runner.git("add", "--", *paths)
            staged = self.runner.git("diff", "--cached", "--quiet")
            if staged.returncode != 0:
                done = self.runner.git("commit", "-m", f"Intake: {title}")
                if done.returncode != 0:
                    raise IntakeError("write_failure", f"git commit failed: {_detail(done)}")
                committed = True
        if committed and not self.record.get("no_push"):
            last: Result | None = None
            for _ in range(PUSH_ATTEMPTS):
                last = self.runner.git("push")
                if last.returncode == 0:
                    pushed = True
                    break
                pull = self.runner.git("pull", "--rebase", "--autostash")
                if pull.returncode != 0:
                    break
            if not pushed:
                detail = _detail(last, 200) if last else ""
                self.say(f"{PHASE_PREFIX} pushing: committed locally but NOT pushed ({detail}); "
                         f"nothing is lost — push again when the remote is reachable")
        note = ("pushed — " + CONVERGES_LINE if pushed
                else "committed, not pushed" if committed else "nothing to commit")
        self.finish("pushing", note, committed=committed, pushed=pushed)
        return "done"

    def phase_report(self) -> str:
        self.phase("report").update({"status": "done"})
        self.save()
        return "done"


#: What `pushing` stages when the vault contract cannot be read (a vault
#: with no question bank, a test fixture): the data roots every vault has.
#: Never `state/` wholesale — `.gitignore` already fences the local parts,
#: but the contract-derived list is the authority when it is available.
FALLBACK_TRACKED_PATHS = ("README.md", "answers", "sources", "outputs", "wiki",
                          "state", "system/question-bank.md",
                          "system/rotation.json", "system/coverage.json")


def tracked_paths(vault_root: Path) -> tuple[str, ...]:
    """The vault paths `pushing` may stage — the contract's list, else the
    fallback roots. Secrets are never on either."""
    try:
        from vault_paths import tracked_vault_paths  # noqa: PLC0415

        return tuple(str(p) for p in tracked_vault_paths(vault_root))
    except Exception:  # noqa: BLE001 — a vault the contract cannot read
        return FALLBACK_TRACKED_PATHS


def _detail(result: Result, limit: int = 600) -> str:
    """What a failed command said: stderr AND stdout, never an empty line."""
    parts = [part.strip() for part in (result.stderr, result.stdout) if (part or "").strip()]
    text = " | ".join(parts) or f"exit {result.returncode}, no output"
    return text[-limit:] if len(text) > limit else text


def _counts_phrase(counts: dict) -> str:
    return (f"{counts.get('new', 0)} new · {counts.get('revision', 0)} revision · "
            f"{counts.get('conflict', 0)} conflict · {counts.get('duplicate', 0)} duplicate")


def synthesis_prompt(task: dict) -> str:
    """The prompt a ready provider drafts one scoped page from — the same
    task the agent is handed keyless (``compile --emit-tasks``), nothing
    more. The answer is the page's narrative markdown, optionally opened by
    a ``Related: a, b`` line (``wiki_compile.parse_agent_narrative``)."""
    rows = []
    for row in task.get("sources") or ():
        if isinstance(row, dict):
            rows.append(f"### {row.get('id')} ({row.get('source')})\n{row.get('body') or ''}")
    related = ", ".join(str(r.get("slug")) for r in task.get("related_candidates") or ()
                        if isinstance(r, dict) and r.get("slug"))
    return (f"Write the wiki page narrative for {task.get('title')} "
            f"({task.get('type')}).\n\n{task.get('instructions') or ''}\n\n"
            "Cite only what the sources below hold. Answer with the page's "
            "narrative markdown only; you may open with one line "
            "`Related: slug, slug` naming related pages from this list: "
            f"{related or '(none)'}\n\n## Sources\n\n" + "\n\n".join(rows))


def _parse_completion(raw: str) -> object:
    """A provider's reading completion, as JSON when it is JSON, else raw."""
    text = str(raw or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    return text


# --------------------------------------------------------------------------
# Starting one
# --------------------------------------------------------------------------

def start(vault_root: Path, text: str, *, kind: str, title: str | None = None,
          witness: str | None = None, record_ref: str | None = None,
          evidence: str | None = None, evidence_source: str | None = None,
          source_label: str = "cli", plan: bool = False, yes: bool = False,
          no_serve: bool = False, no_push: bool = False,
          cap: int = DEFAULT_SYNTHESIS_CAP, runner: Runner | None = None,
          say=print, ask=None, now: str | None = None,
          sensitivity: str | None = None, read: bool = True,
          updates_file: str | None = None,
          update_kind: str | None = None) -> tuple[dict, bool]:
    """Create the record, keep the text, and run as far as the phases go."""
    record = new_record(kind=kind, text=text, title=title, witness=witness,
                        record_ref=record_ref, evidence=evidence,
                        evidence_source=evidence_source, source_label=source_label,
                        plan=plan, yes=yes, no_serve=no_serve, no_push=no_push,
                        cap=cap, now=now, sensitivity=sensitivity, read=read,
                        updates_file=updates_file, update_kind=update_kind)
    folder = intake_dir(vault_root, record["id"])
    _write_vault_text(vault_root, folder / "text.md",
                      text if text.endswith("\n") else text + "\n")
    save_intake(vault_root, record)
    say(f"{PHASE_PREFIX} {record['id']} ({record['kind']}"
        + (f", {record['evidence']} evidence" if record.get("evidence") else "") + ")")
    intake = Intake(vault_root, record, runner=runner, say=say, ask=ask)
    finished = intake.run()
    return intake.record, finished


# --------------------------------------------------------------------------
# --from-updates DIR: one intake per family-letters proposal file (v399)
# --------------------------------------------------------------------------

def landmark_card_count(record: dict) -> int:
    """How many cards an intake ASKS — new, revision, conflict."""
    counts = ((record.get("phases") or {}).get("asking") or {}).get("counts") or {}
    return sum(int(counts.get(kind) or 0) for kind in ("new", "revision", "conflict"))


def update_outcome(record: dict | None) -> str:
    """What one update file is, for the summary: ``flag``, ``waiting``,
    ``landmark`` (the reading asked something) or ``record`` (it did not —
    the file is a source in the vault and nothing more)."""
    if record is None:
        return "flag"
    phases = record.get("phases") or {}
    reading = (phases.get("reading") or {}).get("status")
    if reading not in ("done", "skipped"):
        return "waiting"
    return "landmark" if landmark_card_count(record) else "record"


def _hand_offs(intake: "Intake") -> dict:
    """The keyless hand-off files an agent has already written for a waiting
    intake, as ``run`` inputs. A batch re-run picks them up; nothing else
    about a waiting intake changes."""
    inputs: dict = {}
    phases = intake.record.get("phases") or {}
    completion = intake.folder / "reading.completion.json"
    if (phases.get("reading") or {}).get("status") == "waiting" and completion.is_file():
        inputs["completions"] = completion
    response = intake.folder / "classify.response.json"
    if (phases.get("classifying") or {}).get("status") == "waiting" and response.is_file():
        inputs["response"] = response
    return inputs


def run_updates(vault_root: Path, folder: Path, *, plan: bool = False, yes: bool = False,
                no_serve: bool = False, no_push: bool = False,
                cap: int = DEFAULT_SYNTHESIS_CAP, runner: Runner | None = None,
                say=print, now: str | None = None) -> dict:
    """Run every proposal file in ``folder`` as its own record intake.

    * Each file is ``--record family-letters:<letter ids> --evidence
      document`` with the WHOLE file as the source body, sensitivity
      ``family`` — filed once, through ``ingest-story``.
    * A ``flag`` file writes nothing and prints its question, every run.
    * A file whose intake already exists (same path, same bytes, same
      ``--plan``) is CONTINUED, never started again — so a re-run on the
      same folder files nothing twice. Hand-off files the agent wrote
      (``reading.completion.json``, ``classify.response.json``) are picked up.
    * A finished, non-plan intake moves its file to ``applied/`` with the
      receipt appended; a re-run then no longer sees it.

    Landmark decisions stay per file and per unit: ``--yes`` files only NEW
    units; a revision or conflict waits for ``intake continue <id> --units``.
    """
    import intake_updates as iu  # noqa: PLC0415

    folder = Path(folder).expanduser()
    try:
        files = iu.update_files(folder)
    except FileNotFoundError as exc:
        raise IntakeError("unsupported_input", str(exc)) from exc
    say(f"{PHASE_PREFIX} updates {folder} — {len(files)} file(s)"
        + (" (plan: nothing filed)" if plan else ""))
    known = list_intakes(vault_root)
    rows = []
    for number, path in enumerate(files, 1):
        update = iu.parse_update(path)
        say(f"{PHASE_PREFIX} updates [{number}/{len(files)}] {update['name']} ({update['kind']})")
        if update["kind"] == "flag":
            say(f"  flag-only — writes nothing. Question: {update['question']}")
            rows.append({"file": update["name"], "outcome": "flag", "intake_id": None,
                         "cards": 0, "question": update["question"]})
            continue
        existing = [row for row in known
                    if row.get("updates_file") == str(path)
                    and row.get("text_sha256") == update["sha256"]
                    and bool(row.get("plan")) == bool(plan)]
        if existing:
            record = existing[-1]
            intake = Intake(vault_root, record, runner=runner, say=say)
            if not record.get("done"):
                say(f"  continuing {record['id']}")
                intake.run(**_hand_offs(intake))
            record = intake.record
        else:
            record, _finished = start(
                vault_root, update["text"], kind="record", title=update["title"],
                record_ref=update["record_ref"], evidence="document",
                evidence_source=update["record_ref"], source_label=iu.SOURCE_LABEL,
                plan=plan, yes=yes, no_serve=no_serve, no_push=no_push, cap=cap,
                runner=runner, say=say, now=now, sensitivity=iu.SENSITIVITY,
                read=update["kind"] != "record", updates_file=str(path),
                update_kind=update["kind"])
        outcome = update_outcome(record)
        moved = None
        if record.get("done") and not plan:
            phases = record.get("phases") or {}
            moved = iu.move_applied(path, {
                "intake_id": record["id"], "at": now or now_utc(),
                "source_path": (phases.get("filing") or {}).get("source_path"),
                "receipt_id": (phases.get("landmarks") or {}).get("receipt_id")})
            say(f"  applied → {moved}")
        elif not record.get("done"):
            waiting = [name for name, row in (record.get("phases") or {}).items()
                       if row.get("status") == "waiting"]
            say(f"  waiting: {waiting[0] if waiting else 'in progress'} — "
                f"python3 system/lifehug.py intake continue {record['id']}")
        rows.append({"file": update["name"], "outcome": outcome, "intake_id": record["id"],
                     "cards": landmark_card_count(record),
                     "counts": ((record.get("phases") or {}).get("asking") or {}).get("counts"),
                     "done": bool(record.get("done")),
                     "applied": str(moved) if moved else None})
    summary = {
        "landmark_cards": sum(row["cards"] for row in rows),
        "landmark_files": sum(1 for row in rows if row["outcome"] == "landmark"),
        "flag_only": sum(1 for row in rows if row["outcome"] == "flag"),
        "record_only": sum(1 for row in rows if row["outcome"] == "record"),
        "waiting": sum(1 for row in rows if row["outcome"] != "flag" and not row.get("done")),
        "applied": sum(1 for row in rows if row.get("applied")),
        "files": rows,
    }
    say(f"{PHASE_PREFIX} updates {'plan ' if plan else ''}summary: "
        f"{summary['landmark_cards']} landmark card(s) in {summary['landmark_files']} file(s) · "
        f"{summary['flag_only']} flag-only · {summary['record_only']} record-only · "
        f"{summary['waiting']} waiting · {summary['applied']} applied")
    return summary


def terminal_ask(card: dict) -> bool:
    """A y/n prompt for a plain terminal; used only when stdin is a TTY."""
    print(f"[{card['kind']}] {card['text']}")
    while True:
        answer = input("file this? [y/n/q] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        if answer in ("q", "quit"):
            raise KeyboardInterrupt


# --------------------------------------------------------------------------
# CLI — `lifehug.py intake …` dispatches here
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Intake: here is evidence")
    sub = parser.add_subparsers(dest="verb")

    s = sub.add_parser("start", help="file text on stdin and run the phases")
    kind = s.add_mutually_exclusive_group(required=True)
    kind.add_argument("--story", action="store_true", help="the person's own words")
    kind.add_argument("--witness", metavar="NAME", help="another person's words")
    kind.add_argument("--record", metavar="REF", help="a third-party document; REF names it")
    kind.add_argument("--from-updates", dest="from_updates", metavar="DIR",
                      help="every family-letters proposal file in DIR, each as "
                           "--record family-letters:<ids> --evidence document")
    s.add_argument("--evidence", choices=EVIDENCE_BASES, default=None,
                   help="with --record: how its dates are held (default document)")
    s.add_argument("--evidence-source", dest="evidence_source", default=None)
    s.add_argument("--title", default=None)
    s.add_argument("--source", dest="source_label", default="cli",
                   help="source label on the filed source (telegram, voice, cli, …)")
    s.add_argument("--file", default=None, help="read the text from this file instead of stdin")
    s.add_argument("--plan", action="store_true", help="read and ask; file nothing")
    s.add_argument("--yes", action="store_true",
                   help="file every NEW unit without asking; never a revision or conflict")
    s.add_argument("--no-serve", dest="no_serve", action="store_true")
    s.add_argument("--no-push", dest="no_push", action="store_true")
    s.add_argument("--cap", type=int, default=DEFAULT_SYNTHESIS_CAP,
                   help=f"synthesis pages per intake (default {DEFAULT_SYNTHESIS_CAP})")

    c = sub.add_parser("continue", help="pick an intake up where it stopped")
    c.add_argument("intake_id")
    c.add_argument("--completions", default=None, help="the reading completion file")
    c.add_argument("--response", default=None, help="the classification response file")
    c.add_argument("--units", default=None, help="unit ids to file, comma-separated")
    c.add_argument("--all-new", dest="all_new", action="store_true")
    c.add_argument("--none", action="store_true", help="file no landmark")

    st = sub.add_parser("status", help="one intake's record")
    st.add_argument("intake_id")
    sub.add_parser("list", help="every intake on this machine")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = REPO_DIR
    try:
        if args.verb == "start" and args.from_updates:
            run_updates(root, Path(args.from_updates), plan=args.plan, yes=args.yes,
                        no_serve=args.no_serve, no_push=args.no_push, cap=args.cap)
            return 0
        if args.verb == "start":
            text = (Path(args.file).read_text(encoding="utf-8") if args.file
                    else sys.stdin.read())
            kind = "story" if args.story else ("witness" if args.witness else "record")
            # A y/n prompt only when the text came from a file and a person
            # is at the keyboard; piped text means an agent is driving and
            # decides through `continue --units`.
            ask = terminal_ask if (args.file and sys.stdin.isatty()) else None
            if args.yes or args.plan:
                ask = None
            _record, _finished = start(
                root, text, kind=kind, title=args.title, witness=args.witness,
                record_ref=args.record, evidence=args.evidence,
                evidence_source=args.evidence_source, source_label=args.source_label,
                plan=args.plan, yes=args.yes, no_serve=args.no_serve,
                no_push=args.no_push, cap=args.cap, ask=ask)
            return 0
        if args.verb == "continue":
            record = load_intake(root, args.intake_id)
            ask = terminal_ask if sys.stdin.isatty() and not (args.units or args.all_new or args.none) else None
            intake = Intake(root, record, ask=ask)
            units = [u.strip() for u in (args.units or "").split(",") if u.strip()] or None
            intake.run(completions=Path(args.completions) if args.completions else None,
                       response=Path(args.response) if args.response else None,
                       units=units, all_new=args.all_new, none=args.none)
            return 0
        if args.verb == "status":
            print(json.dumps(load_intake(root, args.intake_id), indent=2, sort_keys=True))
            return 0
        if args.verb == "list":
            for row in list_intakes(root):
                waiting = [n for n, p in (row.get("phases") or {}).items()
                           if p.get("status") == "waiting"]
                state = "done" if row.get("done") else (f"waiting: {waiting[0]}" if waiting else "in progress")
                print(f"{row['id']}  {row.get('kind')}  {state}  {row.get('title') or ''}")
            return 0
    except IntakeError as exc:
        print(f"intake: error ({exc.code}): {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("intake: stopped; continue later with `intake continue <id>`", file=sys.stderr)
        return 130
    parser.print_help()
    return 1


__all__ = [
    "CARD_KINDS", "CONVERGES_LINE", "DEFAULT_SYNTHESIS_CAP", "EVIDENCE_BASES",
    "Intake", "IntakeError", "KINDS", "PHASES", "PHASE_PREFIX", "Result", "Runner",
    "card_counts", "card_kind", "cards_from_proposal", "decide_units",
    "intake_dir", "list_intakes", "load_intake", "new_record", "render_report",
    "save_intake", "scope_tasks", "start", "run_updates", "update_outcome",
    "landmark_card_count", "synthesis_prompt", "viewer_base",
]


if __name__ == "__main__":
    raise SystemExit(main())
