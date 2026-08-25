#!/usr/bin/env python3
"""Reading Room (v204) — the child interaction that dates things from evidence.

An archive's **reading room** is where you consult materials that never leave
the building. That is this session exactly: the person sits down with what
they physically have — an album, a shoebox of prints, a folder of paperwork, a
parent on the phone — reads it out, and the system does the arithmetic.
Nothing is uploaded, nothing is scanned, nothing is ingested (design
consequence 19; holding documents is the connectors question, #580, and the
two stay apart).

The ONE goal (`interactions/README.md` § "The child-interaction paradigm"):
**turn evidence in the room into dated facts.** Not reflection, not meaning —
the parent Conversation's warmth is right and its meaning-making is not the
point here (§12).

Three things make it a session rather than a question:

* **It opens with an inventory, not a memory** (§10). What the person can look
  at decides which questions are cheap, and the right follow-up to a
  photograph is "what's *near* it?" (§5.5's precision inversion — the date is
  on the envelope, which is the thing people throw away).
* **It arrives with a plan and says so once** — `timeline.dig_plan`, the same
  greedy-over-the-residual `keystones` runs, extended to `k` picks with a
  precision grade on each (owner emphasis, 2026-08-24: rank by marginal
  coverage AND ask for the grade of detail that unlocks the derivations — a
  school's *address*, a birthday to the *day*).
* **It recomputes mid-session**, which is the one structural difference from
  every existing interaction: evidence → record → recompute → next ask, and it
  says what just got placed ("that dates nine moments").

It adds **no new output field**. A dated fact files through the Timeline
lane's `placed`; a landmark files through the Landmarks lane's `landmark`.
Two lanes already own those shapes and their validators, so the Reading Room
reuses both rather than minting a third — the paradigm's "exactly ONE additive
field" rule read at its intent, which is *no new vocabulary per child*.

Contract: ``docs/pr-specs/reading-room.md``.
Research: ``system/research/go-deep.md`` (v197), ``landmarks.md`` (v198).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import timeline as _timeline  # noqa: E402
from timeline_interaction import PlaceInvocation  # noqa: E402


class ReadingRoomError(ValueError):
    """A stage, plan or evidence record is unusable."""


# ---------------------------------------------------------------------------
# Stages and knobs.
# ---------------------------------------------------------------------------

VALID_READING_ROOM_STAGES = frozenset({"open", "work", "close"})

#: How many asks one session arrives with (ruling 4). Mirrors
#: `timeline.DIG_PLAN_SIZE`; a test pins the two equal.
PLAN_SIZE = _timeline.DIG_PLAN_SIZE

#: A hard ceiling on asks in one sitting. The person is doing themselves a
#: favour, not filling in a form; the plan is a map, not a script.
MAX_ASKS = 6

#: Two skips in a row ends the session. "I don't have it" is an answer.
STOP_AFTER_SKIPS = 2

#: How many agenda lines the `{agenda}` block may carry.
AGENDA_DISPLAY_LIMIT = 3


def _user_turns(session: object) -> int:
    if not isinstance(session, dict):
        return 0
    turns = session.get("turns")
    if not isinstance(turns, list):
        return 0
    return sum(1 for t in turns if isinstance(t, dict) and t.get("role") == "user")


def reading_room_stage_for_session(session: object, *, user_leaving: bool = False,
                                   plan_exhausted: bool = False,
                                   skip_streak: int = 0) -> str:
    """``open`` on the first turn, ``close`` when done, ``work`` in between.

    Pure, and derived from the transcript — never stored. The caller supplies
    the three things only it can know: the router's departure signal, whether
    the recomputed plan has anything left, and how many times in a row the
    person has said they do not have it.
    """
    turns = _user_turns(session)
    if turns <= 0:
        return "open"
    if user_leaving or plan_exhausted:
        return "close"
    if skip_streak >= STOP_AFTER_SKIPS or turns >= MAX_ASKS:
        return "close"
    return "work"


# ---------------------------------------------------------------------------
# The inventory — the opening move (§5, §10, design consequence 3).
# ---------------------------------------------------------------------------

#: The four sessions that are genuinely different, in the research's own
#: terms: a shoebox of prints, one dated document, a relative on the phone,
#: and nothing at all.
INVENTORY_KINDS = ("photos", "documents", "relative", "nothing")

INVENTORY_OPENER = (
    "What do you have in front of you? An album, a box of prints, a folder of "
    "paperwork, somebody on the phone — or nothing at all, which is also fine."
)

#: §5.5's inversion, in one clause. The date is usually not on the photograph.
NEAR_THE_PHOTO = "and whatever is near it — envelopes, backs, the folder it came in"


def render_inventory(inventory: object) -> str:
    """The `{inventory}` block: what the person said they have, verbatim-ish."""
    text = str(inventory or "").strip()
    if not text:
        return "(not asked yet — this turn is the inventory question)"
    return text[:400]


# ---------------------------------------------------------------------------
# The agenda — the plan, said once (`arc_walk`'s opener shape).
# ---------------------------------------------------------------------------

def render_agenda(plan: object, *, limit: int = AGENDA_DISPLAY_LIMIT) -> str:
    """The `{agenda}` block — each item as WHAT IT WOULD UNLOCK.

    Never a count of what remains, never a percentage, never a queue. The gain
    number is stated as the research's own sentence: "if we can place this, N
    other things fall into place" (§8.3).
    """
    asks = (plan or {}).get("asks") if isinstance(plan, dict) else None
    lines = []
    for row in (asks or ())[:max(int(limit), 0)]:
        if not isinstance(row, dict):
            continue
        gain = int(row.get("would_place") or 0)
        label = str(row.get("label") or row.get("ref") or "").strip()
        tail = f" — would place {gain} other things" if gain > 1 else ""
        lines.append(f"- {label}: {row.get('ask', '')}{tail}")
    return "\n".join(lines) if lines else "(nothing outstanding — follow them)"


def next_ask(plan: object) -> dict | None:
    """The one item to ask about this turn — the head of the recomputed plan."""
    asks = (plan or {}).get("asks") if isinstance(plan, dict) else None
    for row in asks or ():
        if isinstance(row, dict) and row.get("ask"):
            return dict(row)
    return None


def render_next_ask(plan: object) -> str:
    """The `{next_ask}` block: one ask, its precision grade, and what it buys."""
    row = next_ask(plan)
    if row is None:
        return "(nothing on the plan — follow whatever they are holding)"
    return str(row.get("ask") or "").strip()


# ---------------------------------------------------------------------------
# The recompute — the one structural novelty (§10, design consequence 8).
# ---------------------------------------------------------------------------

def recompute_plan(data: dict, *, roster: object = None, k: int = PLAN_SIZE,
                   resolved: object = ()) -> dict:
    """Re-run the plan against the graph AS IT NOW STANDS.

    Pure, and stateless: it takes the current timeline data and returns a new
    plan. `resolved` subtracts the unknown keys whose placement this session
    filed but which the caller's `data` may not have picked up yet — the write
    is host-side and can lag a turn. Nothing is persisted (design consequence
    13); a plan assembled a second later may legitimately be shorter, and that
    is the design, not drift.
    """
    done = {str(key) for key in (resolved or ()) if str(key)}
    plan = _timeline.dig_plan(data, roster, k)
    if not done:
        return plan
    asks = []
    for row in plan.get("asks") or ():
        keys = [key for key in (row.get("unknown_keys") or ()) if key not in done]
        if not keys:
            continue
        row = dict(row)
        row["unknown_keys"] = keys
        row["would_place"] = row["gain"] = len(keys)
        asks.append(row)
    plan = dict(plan)
    plan["asks"] = asks
    plan["remaining"] = max(int(plan.get("remaining") or 0) - len(done), 0)
    return plan


def placement_gain_sentence(before: object, after: object) -> str:
    """"That dates nine moments." — the only progress feedback that belongs here.

    Counts of what REMAINS are forbidden; a count of what an answer just
    UNLOCKED is the whole point (§8.3, and the owner's own sentence).

    v207: the clause itself is `cross_dating.moment_clause` — the landmark and
    timeline lanes say the same true thing at their own filing beat, and one
    definition is how the two can never drift into two wordings.
    """
    import cross_dating as _xd  # noqa: PLC0415  (avoids an import cycle)

    try:
        gap = int((before or {}).get("remaining", 0)) - int((after or {}).get("remaining", 0))
    except (TypeError, ValueError, AttributeError):
        return ""
    if gap <= 0:
        return ""
    return f"That {_xd.moment_clause(gap)}."


# ---------------------------------------------------------------------------
# Filing — the two fields this lane REUSES, and the honesty each basis owes.
# ---------------------------------------------------------------------------

#: A photograph's contextual date is a WINDOW by construction (§5.1), and a
#: relative's memory is second-hand (§6.4). Neither can be `certain`, whatever
#: the model writes. A printed date can be — that is the whole reason
#: `document` outranks `stated`.
CONFIDENCE_CEILING = {"photo": "approximate", "relative": "approximate"}


def normalize_evidence_record(record: object, *, witness: object = None) -> dict | None:
    """Apply what each evidence basis honestly owes, then return the record.

    * `photo` and `relative` are capped at `approximate` — the system says on
      the record it writes that a photograph gives a window, not a day
      (design consequence 21).
    * `relative` gains a witness provenance entry naming who said it, so the
      claim is attributable and two relatives corroborating count as two
      independent origins in `chronology.claim_score` for free.

    Returns ``None`` for anything unusable, exactly as every layer in this
    family returns ``None`` rather than raising.
    """
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None
    value = parsed.to_dict()
    ceiling = CONFIDENCE_CEILING.get(value.get("basis") or "")
    if ceiling is not None:
        order = chrono.CONFIDENCES
        if order.index(value["confidence"]) < order.index(ceiling):
            value["confidence"] = ceiling
    if value.get("basis") == "relative":
        provenance = list(value.get("provenance") or ())
        if chrono.witness_slug(value) is None and witness:
            entry = chrono.witness_provenance(
                (witness or {}).get("slug") if isinstance(witness, dict) else witness,
                name=(witness or {}).get("name") if isinstance(witness, dict) else None,
            )
            if entry is not None:
                provenance.append(entry)
        value["provenance"] = provenance
    return value


def validate_evidence(value: object, *, anchors: object = (),
                      witness: object = None) -> dict | None:
    """Closed validation of a Reading Room placement.

    Delegates the vocabularies, EDTF parseability and anchor membership to
    `timeline_interaction.validate_placed` — one definition, two lanes — then
    applies :func:`normalize_evidence_record`. There is no second vocabulary
    here and there must never be one.
    """
    import timeline_interaction as _ti  # noqa: PLC0415

    placed = _ti.validate_placed(value, anchors=anchors)
    if placed is None:
        return None
    return normalize_evidence_record(placed, witness=witness)


def filing_invocations(turn: object, *, source: str = "", description: str = "",
                       period: str = "") -> list[PlaceInvocation]:
    """The complete calls the host runs to file whatever this turn produced.

    The package NAMES, the host WRITES — the same split every child uses. A
    `placed` record goes through `timeline-place`, a `landmark` through
    `landmark-record`, and this lane owns neither verb.

    Every row is a `timeline_interaction.PlaceInvocation` — argv AND the stdin
    that command reads — so a host can run the list uniformly::

        subprocess.run([..., *inv.argv], input=inv.stdin_text, text=True)

    `timeline-place` reads its description on stdin and exits 1 without it;
    `landmark-record` takes everything as flags and carries `stdin_text=""`.
    Returning bare argv is what let the one wired host drop the description
    (lifehug#223), and this lane will not re-plant it.
    """
    import landmarks_interaction as _li  # noqa: PLC0415
    import timeline_interaction as _ti  # noqa: PLC0415

    if not isinstance(turn, dict):
        return []
    out: list[PlaceInvocation] = []
    placed = turn.get("placed")
    if placed:
        invocation = _ti.place_invocation(placed, source=source, description=description,
                                          period=period)
        if invocation is not None:
            out.append(invocation)
    landmark = turn.get("landmark")
    if landmark:
        argv = _li.landmark_invocation(landmark)
        if argv:
            out.append(_ti.PlaceInvocation(argv, ""))
    return out


# ---------------------------------------------------------------------------
# The close — homework as an ordinary note, re-derived (design consequence 13).
# ---------------------------------------------------------------------------

def render_dig_lists(plan: object) -> list[str]:
    """Every witness's dig list, as the lines their wiki page will carry.

    The list is NOT stored: `wiki_compile.apply_dig_lists` re-derives it from
    `timeline.timeline_data()["reading_room"]` on every compile and renders it
    into that person's existing `## Open Questions` section (ruling 3). There
    is no deferral machine, no inbox, and no outstanding-item tracking — v196
    deleted one deliberately and the rule stands.
    """
    lists = (plan or {}).get("witness_lists") if isinstance(plan, dict) else None
    lines: list[str] = []
    for slug in ((plan or {}).get("witness_order") or list(lists or ())):
        entry = (lists or {}).get(slug)
        rendered = _timeline.render_dig_list(entry)
        if rendered:
            lines.extend(rendered)
    return lines


def describe_close(plan: object) -> str:
    """One plain sentence naming who would know what, or nothing at all."""
    lists = (plan or {}).get("witness_lists") if isinstance(plan, dict) else None
    order = ((plan or {}).get("witness_order") or list(lists or ()))[:2]
    named = [str((lists or {}).get(slug, {}).get("name") or slug) for slug in order]
    if not named:
        return ""
    if len(named) == 1:
        return f"{named[0]} would know some of the rest — that list is on their page."
    return (f"{named[0]} and {named[1]} would know some of the rest — those lists "
            f"are on their pages.")


# ---------------------------------------------------------------------------
# Lints (Design §F).
# ---------------------------------------------------------------------------

READING_ROOM_LINT_CLASSES = (
    "reading_room_gates.artifact_carries_the_burden",
    "reading_room_gates.no_pressure",
    "reading_room_gates.accepts_i_will_find_out",
    "reading_room_gates.one_ask_per_turn",
    "reading_room_gates.never_proposes_a_date",
)

#: Asking the MEMORY to do the work the paper is already doing. "What does the
#: back of it say?" beats "do you remember when that was?" every time — and
#: the memory version is also the configuration that manufactures false
#: memories when it is backed by the person's own evidence (§4.3).
_MEMORY_FIRST_RES = (
    re.compile(r"\bdo you (?:remember|recall) (?:when|what year|the year|the date)\b",
               re.IGNORECASE),
    re.compile(r"\btry to (?:remember|recall|think back)\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s| is) your best guess\b", re.IGNORECASE),
    re.compile(r"\bhow (?:many years|long) ago (?:was|were)\b", re.IGNORECASE),
)

#: The deferral machine, in voice form. "I'll find out" is a complete answer
#: and ends there; a system that tracks it has grown an inbox (§12, design
#: consequence 13).
_TASK_TRACKING_RES = (
    re.compile(r"\b(?:I'?ll|I will) (?:remind you|follow up|check back|add (?:that|it) to)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:don'?t forget|make sure you|be sure to) (?:to )?ask\b",
               re.IGNORECASE),
    re.compile(r"\blet me know (?:when|once) you (?:find|hear|get)\b", re.IGNORECASE),
    re.compile(r"\b(?:I'?ll|we'?ll) (?:put|add) (?:that|it) on (?:your|the) list\b",
               re.IGNORECASE),
)

_SPAN_LIMIT = 400


def lint_reading_room_reply(text: object, *, stage: str) -> list[dict]:
    """Deterministic findings for the five ``reading_room_gates.*`` classes.

    Pure — no model, no I/O. Findings share `conversation_lints.lint_turn`'s
    shape (`lint` / `detail` / `span`) so one caller can merge these with the
    timeline lane's and the landmarks lane's uniformly. An unrecognized stage
    is treated as ``"work"`` — fail toward the strictest ordinary rule.
    """
    import landmarks_interaction as _li  # noqa: PLC0415
    import timeline_interaction as _ti  # noqa: PLC0415

    body = text if isinstance(text, str) else ""
    if stage not in VALID_READING_ROOM_STAGES:
        stage = "work"
    findings: list[dict] = []

    def _first(patterns) -> object:
        for pattern in patterns:
            match = pattern.search(body)
            if match:
                return match
        return None

    match = _first(_MEMORY_FIRST_RES)
    if match:
        findings.append({
            "lint": "reading_room_gates.artifact_carries_the_burden",
            "detail": "ask what the artifact says, never what they remember — "
                      "'what does the back of it say?' beats 'do you remember "
                      "when that was?' (go-deep.md §4.3, §10)",
            "span": [match.start(), match.end()],
        })

    # The shared definition, third caller (recurring-defect doctrine).
    match = _li.pressure(body)
    if match:
        findings.append({
            "lint": "reading_room_gates.no_pressure",
            "detail": "they are doing themselves a favour — never refuse a "
                      "skip, never lean on them, never ask twice",
            "span": [match.start(), match.end()],
        })

    match = _first(_TASK_TRACKING_RES)
    if match:
        findings.append({
            "lint": "reading_room_gates.accepts_i_will_find_out",
            "detail": "'I'll find out' is a complete answer and ends there — "
                      "no reminders, no follow-ups, no list. A dig list is a "
                      "page, not a queue (go-deep.md §12)",
            "span": [match.start(), match.end()],
        })

    if stage != "close" and body.count("?") > 1:
        findings.append({
            "lint": "reading_room_gates.one_ask_per_turn",
            "detail": "one thing at a time — a turn that asks two things while "
                      "someone is holding a photograph gets neither answered",
            "span": [0, min(len(body), _SPAN_LIMIT)],
        })

    # go-deep.md §4.3, Lindsay et al. 2004: the shared rule, from the shared
    # definition. This lane is the exact configuration the study describes —
    # a dating probe backed by the person's own evidence — so it is the lane
    # that can least afford to propose a date.
    proposal = _ti.proposes_a_date(body)
    if proposal is not None:
        findings.append({
            "lint": "reading_room_gates.never_proposes_a_date",
            "detail": "never name a date and ask them to agree — elicit the "
                      "reading and do the arithmetic",
            "span": [proposal.start(), proposal.end()],
        })
    return findings


# ---------------------------------------------------------------------------
# The read-only plan verb.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Print the Reading Room plan.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--k", type=int, default=PLAN_SIZE)
    args = parser.parse_args(argv)
    plan = _timeline.dig_plan(_timeline.timeline_data(), None, args.k)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True, default=str))
        return 0
    print(render_agenda(plan))
    for line in render_dig_lists(plan):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
