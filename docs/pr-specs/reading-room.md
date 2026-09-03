# The Reading Room (v204)

**Removed 2026-09-03 (owner ruling R4a, `lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`):** the Reading Room / Go Deep leaves the product together with Go Dig; this file is deleted in Cut 2c. Add Landmark (an `offer` mode of `landmarks`, Cut 6a) replaces this line of work. Kept as history until then.

Contract for `feat/reading-room`. Design authority: `docs/adr/0025-the-reading-room.md`.
Research: `system/research/go-deep.md` (v197), `system/research/landmarks.md` (v198).
Owner rulings: lifehug-platform#593 (2026-08-24).

## §A — What ships

**The math and the bases** (`system/chronology.py`, `system/timeline.py`):
three evidence bases with flat weights and a witness provenance entry;
`timeline.dig_plan` as the greedy-over-the-residual plan extended to `k` with
a precision grade and a witness partition; `timeline.witness_for`;
`timeline_data()["reading_room"]` as an additive, derived block.

**The interaction** (`interactions/reading_room/`, `system/reading_room.py`,
`system/reading_room_evals.py`): stages `open | work | close`, an
inventory-first opener, a plan said once, a mid-session recompute that says
what just got placed, and a close that names who would know the rest.

**The homework** (`system/wiki_compile.py`, `system/question_candidates.py`):
each witness's dig list re-derived on compile into their own
`## Open Questions`, marked so the harvester never turns it into one of the
owner's own questions.

## §B — The plan

`dig_plan(data, roster, k=3) -> {asks, witness_lists, witness_order,
witness_lines, unreachable, remaining, open_unknowns, k}`.

Each ask carries `{ref, anchor, question_id, label, probe, ask,
precision_target, precision_unlocks, would_place, gain, width_gain,
remaining, unknown_keys, witness, anchors}`.

Each dig-list item carries `{unknown_key, question, unlocks,
precision_target, width}`.

## §C — The precision grade

Closed vocabulary `timeline.PRECISION_TARGETS`; each grade carries the clause
that says what it buys (`PRECISION_UNLOCKS`). The ladder: a birthday is asked
to the **day**; a school is asked for its **address**; otherwise the unknown's
kind decides, defaulting to `year`.

## §D — The `TurnShape` gate

`TurnShape.reading_room_stage`, default `None`, LAST field so positional
callers are unaffected. It opens BOTH the `placed` and `landmark` output keys.
Required test: `test_output_contract_block_byte_identical_without_reading_room_stage`.
The advertised basis vocabulary is derived from `chronology.BASES`.

## §E — Filing

`reading_room.filing_invocations` → `lifehug.py timeline-place` /
`landmark-record`. The package names, the host writes. This lane owns no write
verb of its own.

## §F — Lints and the seat gate

Five `reading_room_gates.*` classes, all gated at 1.0:
`artifact_carries_the_burden`, `no_pressure` (shared definition:
`landmarks_interaction.pressure`), `accepts_i_will_find_out`,
`one_ask_per_turn`, `never_proposes_a_date` (shared definition:
`timeline_interaction.proposes_a_date`). Six required goldens.

## §G — Launch and verify

```bash
python3 system/lifehug.py reading-room-evals --json   # seat gate, must pass
python3 system/lifehug.py reading-room-plan           # the plan + the dig lists
python3 -m pytest tests/test_reading_room.py -q       # the math and the lane
python3 -m pytest tests/ -q                           # everything else
```

Expected: the seat gate reports `"passed": true`; the plan prints an agenda
whose lines state what each ask would unlock and never what remains; every
dig-list line carries the Reading Room marker and exactly one footer line.
