---
title: Timeline
parent: The Interaction Pattern
nav_order: 7
---

# Timeline Interaction

## 1. What it does

Timeline is the conversation you get when you press Play on a hole in your
timeline — a stretch with nothing placed in it, a moment that floats free, an
era with no order. It is the fifth child of Conversation, and its one goal is
**placing a memory in time without ever demanding a year** (v195,
`docs/pr-specs/timeline-chronology.md`; platform design brief `#581`).

It never opens with "what year was that". Dating a memory is reconstruction,
not recall: people work out *when* from what else was true then — where they
were living, what work they were doing, who was around. So the conversation
asks about those, and the date falls out. If you say you were about five and
the system already knows your birthday, it does the arithmetic and says the
answer back as an inference you can correct.

A **bounded interval is a real answer.** "Sometime between the move and the
baby" is a finding, not a failure, and it is stored as one. The ladder climbs
era → year-range → year → season → month only while it stays cheap, and stops
at the first rung you hold without hedging — a hedged month is worse than a
confident season.

**"I'll find out" is a real state.** Say you will ask your mother and the
unknown goes quiet: it keeps its star and its leverage, it is never counted as
outstanding, and nothing raises it again.

**Passive users are untouched.** The daily single question works exactly as it
did; this Interaction runs only when an unknown is Played. Mechanically the
gate is `TurnShape.timeline_stage`, which defaults to `None`, and with it
`None` the turn's output contract is byte-identical to v194.

## 2. The behavior authority

The contract below is the file the runtime sends to the model, verbatim — not a
description of it (see [the Interaction Pattern](index.md) §3).

<!-- embed: interactions/timeline/prompt/behavior.md -->
# Behavior contract — Timeline extension

The inherited Conversation contract governs every visible reply. These rules
add the Timeline responsibility.

1. **Never open with a year.** Not "what year was that", not "roughly what
   year", not "can you give me a decade". Dating is reconstructive inference,
   so a year prompt buys a rounded guess that drifts later than the truth.
   Open with the moment itself, then with where they were living or what work
   they were doing — the things a life is actually indexed by.
2. **One question per reply.** Receive what they said first; ask the next
   thing second. Two questions turns placing a memory into an interrogation.
3. **Bound before you pin.** Two bounds beat one guess. "Was that before or
   after you moved?" and "had she been born yet?" give an interval, and an
   interval is storable, honest, and often all there ever was.
4. **Offer bounds; never demand a point.** "Spring 1998 — or is 'sometime
   97–99' more honest?" lets them choose the precision they can actually
   hold. Asking them to pick a month they do not have is asking them to make
   one up.
5. **Prefer their landmarks to the world's.** A move, a wedding, a birth, a
   job — their own turning points work at least as well as public events, and
   a public event only helps when it actually disrupted *their* daily life.
6. **Climb only while it is cheap.** Era → year-range → year → season →
   month, and stop at the first rung they hold without hedging. A hedged
   month is worse than a confident season. Stop when two probes in a row add
   no new bound. Stop instantly on any distress: dating is never worth the
   relationship.
7. **"I'll find out" is a real answer.** When they say they will ask their
   mother, or check a photo, receive it warmly, say it will keep, and ask
   nothing further about it. It is not a decline and it is not a debt, and
   you never raise it again in this episode.
8. **Never invent a date.** Every year you say out loud must be one they gave
   you or one that is already on their own timeline. If the arithmetic gives
   you a year — their age against their birthday, a landmark and a
   before/after — say it back as an inference and let them correct it.
9. **Both accounts survive.** If what they say now disagrees with something
   the timeline already holds, say so plainly, keep both, and ask which they
   trust — never overwrite, never quietly pick one, and never treat the
   disagreement as a mistake. What they remember differently is itself worth
   knowing.

## Placement doctrine

A timeline is how a person sees the shape of their own life, not a database
to complete. So a placement episode is short, it ends the moment the memory
is placed well enough for its slot, and nothing is ever "still missing". The
holes are interesting; they are not failures, and they are never described as
falling behind.
<!-- /embed -->

## 3. The playbook, the anchors, and the stage

| Concern | Where |
|---|---|
| What a Play points at | `timeline.unknowns(data)` → `{kind, key, label, probe, deferred, ...}`; kinds are `timeline.UNKNOWN_KINDS` — `era_gap` plus the seven `compute_gaps` already emitted |
| The person's landmarks | `timeline_interaction.anchors_for_person(birth_date=…, periods=…, places=…, events=…)`, rendered into `{anchors}` by `render_anchors`. Birthday, residences with spans, eras with spans, dated landmark moments — the life-history calendar as text, and the ONLY dates the model may repeat |
| The next question | `timeline_interaction.choose_probe(unknown, anchors=…, precision_so_far=…, asked_steps=…)` walks `PLAYBOOK_STEPS`: content → residence → role → parallel domain → sequence → landmark → season → bounds → convergence → defer. Rungs needing a landmark are skipped when there is none |
| When the ladder stops | `TARGET_GRANULARITY` per unknown kind — a gap between eras needs a year, a thin lineup only needs an era. At or finer than target, the probe becomes `convergence` |
| Which stage this turn is in | `timeline_interaction.timeline_stage_for_session(session, user_leaving=…, placement_settled=…, no_new_bound_streak=…)` → `open` before the first assistant turn, `close` on a departure, a settled placement, two unproductive probes, or the probe ceiling; `place` otherwise <!-- parity: timeline_interaction.STOP_AFTER_UNPRODUCTIVE_PROBES = 2 --> <!-- parity: timeline_interaction.MAX_PROBES = 4 --> |
| The prompt the caller replays verbatim | `interactions/timeline/prompt/turn-instructions.md`, substituting `{timeline_stage}`, `{unknown_label}`, `{probe}`, `{anchors}`, `{precision_so_far}` |
| The five lints | `timeline_interaction.lint_timeline_reply` → `timeline_gates.*`: never open by asking for a year; at most one question; offer bounds rather than demand a point; accept a deferral without pressing; never assert a year nobody supplied |

"Never pressure" is deliberately absent from that list: the parent
Conversation contract and `arc_walk`'s `no_pressure` already own it, and a
second definition of one rule is the defect the recurring-defect doctrine
forbids.

## 4. Filing: what does a placement write?

One additive output field, `placed`, carries either a date record, or
`{"deferred": true}`, or null. Two layers validate it, exactly as every other
child's field is validated: `conversation_delivery._parse_placed` owns shape
and no vocabulary and never raises;
`timeline_interaction.validate_placed(value, anchors=…)` owns the three closed
vocabularies, EDTF parseability, and **exact** membership of every anchor key
in the anchors this episode actually offered — an invented anchor drops the
whole record rather than filing something wrong.

The package names the date; the host writes it.
`timeline_interaction.place_invocation` builds the exact argv for the write
path that already existed: `lifehug.py timeline-place <source> --period <slug>
[--date <edtf>] [--basis <basis>] [--anchor <key>]…`, which files a `--kind
date` correction source (the durable half) and saves the display pin (which
auto-retires once classification catches up).

## 5. Where it lives

| Concern | Location |
|---|---|
| Registration | `interactions/registry.json` (`timeline`) |
| Definition | `interactions/timeline/` |
| Runtime authority | `system/timeline_interaction.py` |
| The date primitive | `system/chronology.py` |
| Unknowns, leverage, keystones, deferred | `system/timeline.py` |
| Plan a timeline Play (read-only) | `lifehug.py arc-plan-target --timeline [--era <slug>] [--json]` |
| The write path | `lifehug.py timeline-place ... [--date] [--basis] [--anchor]` |
| Goldens | `interactions/timeline/evals/goldens/timeline_*.json` |
| Independent evals | `lifehug.py timeline-evals --json` |
| Guard tests | `tests/test_chronology.py`, `tests/test_timeline_dates.py`, `tests/test_timeline_unknowns.py`, `tests/test_timeline_interaction.py`, `tests/test_timeline_evals.py` |

The package declares role tiers but no default concrete seat. The five
`timeline_gates.*` compliance classes require perfect scores over ten recorded
goldens — including the **skeleton episode** (birthday, then the places lived
by age, which dates most of a timeline by inference) and a contradiction case
where both accounts survive. They score with or without a live provider; an
unavailable provider skips loudly and never seats by default.

## 6. Decisions

- [ADR 0024 — Chronology with basis: dates as intervals, asking anchor-first](../../adr/0024-chronology-with-basis.md) — the split doctrine, the closed vocabularies, contradictions that keep both claims, derived order, keystones, and the deferred memory.
- [ADR 0018](../../adr/0018-candidate-placement.md), fifth amendment — `placed` as the fifth instance of the additive-field discipline.
- [ADR 0023](../../adr/0023-arc-walking.md) — the sibling whose stage/caller-fact shape this child copies line for line.
