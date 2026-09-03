# Reading Room Interaction

**Removed 2026-09-03 (owner ruling R4a, `lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`):** the Reading Room / Go Deep leaves the product together with Go Dig; this file is deleted in Cut 2c. Add Landmark (an `offer` mode of `landmarks`, Cut 6a) replaces this line of work. Kept as history until then.

`reading_room` is an independently registered, auditable Interaction for the
**evidence-driven dating session**. It exact-composes Conversation by
reference and owns only the one goal Conversation cannot carry: **turn what
the person physically has in the room into dated facts.**

**The name is literal.** An archive's reading room is where you consult
materials that never leave the building — you sit down with what you have, and
nothing is taken from you. That is the whole posture: in-app, opt-in, chosen,
and nothing ingested. The button verb is **Go Deep**; the noun is the Reading
Room; the per-witness homework is a **dig list** (owner ruling, 2026-08-24).

**It opens with the room, not the memory.** A shoebox of prints, one report
card, a parent on speakerphone, and nothing at all are four different
sessions, and what the person can physically look at decides which questions
are cheap (`system/research/go-deep.md` §5, §10). And when they name a
photograph, the follow-up is what is **near** it: the date is on the envelope,
and the envelope is what people throw away (§5.5).

**The artifact carries the burden, not their memory.** "What does the back say?"
beats "do you remember when that was?" every time — and not only because it
works better. True photographs plus suggestive interviewing produce false
memories in about two thirds of participants, and a dating probe backed by the
person's own evidence is that configuration exactly (Lindsay et al. 2004,
§4.3). So this lane elicits *readings* and does the arithmetic itself, and
`timeline_interaction.proposes_a_date` — the one shared definition, now run by
three lanes — is the mechanical form of "never name a date and ask them to
agree".

**Rank by coverage; ask for the grade** (owner emphasis, 2026-08-24). The plan
is greedy over the RESIDUAL graph, not a top-N leverage list: on real vault
data one star's resolve set was a strict subset of the other's, so the second
star's marginal gain was exactly zero (§8.2). And each pick names the
**precision grade** that unlocks the derivations behind it — a school is a
name until you have its *address*, and then it is a district, and a district
keeps records with exact years in them (§5.3). Ranking is on the continuous
width-sum with the count displayed, because a threshold metric is not
submodular and greedy stalls on it (§8.4, warning 3).

**It recomputes mid-session.** Evidence → record → recompute → next ask. That
is the one structural difference from every existing interaction, and it is
why a Reading Room is a session rather than a question. `recompute_plan` is a
pure function over the current graph; nothing about the plan is persisted.

**Three new bases.** `chronology.BASES` gains `document`, `photo` and
`relative`, weighted flat (ruling 5): `document 7.0 · stated 6.0 ·
relative 5.5 · age 5.0 · photo 4.5`. A printed date outranks a stated one
because it is not a reconstruction. A relative sits just under `stated`
because proxy report is meant to be used *with* the index report, not instead
of it (Straughen et al. 2013, §6.4). A photograph sits under both because a
contextual date **bounds** rather than names — and the record says so, out
loud, on itself (§11.21).

**A witness is someone living who was there**, inferred from roster facts the
person already gave (`relationship`, `living`) joined on edges
`dependency_index` already walks. No new state. Urgency is an ORDERING by
generation, oldest first, and nothing else: never a label on a person, and
never one word about anybody's mortality (§6.1, §9.3).

**Homework is a page, not a queue.** The close names who would know what; the
dig list itself is re-derived on every compile and rendered into that person's
existing `## Open Questions` section (ruling 3). There is no deferral machine,
no inbox and no outstanding-item tracking — v196 deleted one deliberately and
the rule stands. "I'll find out" is an ordinary, complete answer.

**Passive users are untouched.** The daily single question keeps working
exactly as it did; this Interaction runs only when the row is Played.
Mechanically: `TurnShape.reading_room_stage` defaults to `None` and the output
contract is then byte-identical to v203.

**Platform twin.** A host REPLAYs this package and reads exactly these —
nothing else is a contract (the shared shape: `interactions/README.md`
§ "The child-interaction paradigm"):

| What | Where |
|---|---|
| The three evidence bases and their weights | `chronology.BASES`, `chronology.EVIDENCE_BASES`, `chronology.BASIS_WEIGHT` |
| The witness, on a record | `chronology.witness_provenance(slug, name=…, said_at=…)`, `witness_slug`, `witness_name`, `WITNESS_SOURCE_PREFIX` |
| The plan a host renders | `timeline.dig_plan(data, roster, k)`; `timeline.timeline_data()["reading_room"]` |
| The precision grade | `timeline.PRECISION_TARGETS`, `PRECISION_UNLOCKS`, `PRECISION_TARGET_BY_KIND`, `timeline.precision_target_for`, `timeline.precision_ask` |
| The ranking quantity | `timeline.unknown_width` (continuous), with the count shown as `would_place` |
| The witness join | `timeline.witness_for(ref, data, roster)`, `timeline.WITNESS_GENERATION_ORDER` |
| The dig list, and its one footer line | `timeline.render_dig_list(entry)`, `timeline.DIG_LIST_MARKER`, `timeline.DIG_LIST_FOOTER`, `timeline.WITNESS_LIST_CAP`, `timeline.WITNESS_LINE_CAP` |
| The row's two witness lines | `timeline.timeline_data()["reading_room"]["witness_lines"]` |
| The `{reading_room_stage}` this turn is in | `reading_room.reading_room_stage_for_session(session, user_leaving=…, plan_exhausted=…, skip_streak=…)` |
| The `{inventory}`, `{agenda}` and `{next_ask}` blocks | `reading_room.render_inventory`, `render_agenda`, `render_next_ask`, `next_ask` |
| The mid-session recompute | `reading_room.recompute_plan(data, roster=…, k=…, resolved=…)` |
| The one sentence about what just got placed | `reading_room.placement_gain_sentence(before, after)` |
| The two output fields this lane REUSES | `conversation_delivery.parse_turn_output(...)["placed"]` and `["landmark"]`, both enabled by `TurnShape(reading_room_stage=…)` — this Interaction mints NO field of its own |
| Closed validation of those fields | `reading_room.validate_evidence(value, anchors=…, witness=…)` (delegates to `timeline_interaction.validate_placed`) and `landmarks_interaction.validate_landmark` |
| What each basis honestly owes | `reading_room.normalize_evidence_record`, `reading_room.CONFIDENCE_CEILING` |
| The five reading-room lints | `reading_room.lint_reading_room_reply(text, stage=…)`; `reading_room.READING_ROOM_LINT_CLASSES`. The fifth, `never_proposes_a_date`, is SHARED — its one definition is `timeline_interaction.proposes_a_date`. `no_pressure` is shared too: `landmarks_interaction.pressure` |
| Filing an accepted record | `reading_room.filing_invocations(turn, source=…, description=…, period=…, placement_key=…)` → `lifehug.py timeline-place` / `landmark-record`, each as a `PlaceInvocation(argv, stdin_text)` the host runs with `input=` (lifehug#223) |
| The close, and the homework | `reading_room.render_dig_lists(plan)`, `reading_room.describe_close(plan)`; rendered by `wiki_compile.apply_dig_lists` into the witness's own `## Open Questions` |
| The harvest guard | `question_candidates._is_dig_list_line` — a dig list is addressed to the WITNESS and must never enter the owner's own queue |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{reading_room_stage}`, `{inventory}`, `{agenda}`, `{next_ask}`, `{anchors}` |
| The read-only plan verb | `lifehug.py reading-room-plan [--json] [--k N]` |

The FILING is entirely host-side, and through verbs this lane does not own:
the package names the date and its basis, the host writes it.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py reading-room-evals --json
```

See `docs/adr/0025-the-reading-room.md`, `docs/pr-specs/reading-room.md`, and
`system/research/go-deep.md`.
