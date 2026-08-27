# Timeline Interaction

`timeline` is an independently registered, auditable Interaction for placing a
memory in time. It exact-composes Conversation by reference and owns only the
one goal Conversation cannot carry: **place a memory in time without ever
demanding a year.**

**Asking stays anchor-first; storage gains real dates.** The package's old
doctrine — the planner's `BANNED_PHRASE`, the compiler's "absolute years are
deliberately NOT inferred" — was right about ASKING and wrong about STORAGE
(ADR 0024, owner ruling 1). Dating a memory is reconstructive inference
(Friedman 1993), so a year prompt buys a rounded, telescoped guess and stays a
lint. But a date the system can DERIVE from what the person did say — their
age against their birthday, a landmark plus a before/after — is real, and it
is stored as an interval with a granularity, a confidence, a basis, its
anchors, and its provenance (`chronology.DateRecord`).

**An interval is a finding, not a failure.** Historians bound before they pin:
*terminus post quem* and *terminus ante quem* (`system/research/chronology.md`
§1). So the ladder offers bounds rather than demanding points, and it stops at
the first rung the person holds without hedging — a hedged month is worse than
a confident season (Huttenlocher, Hedges & Bradburn 1990).

**The playbook is the sourced one.** content → residence → role → parallel
domain → sequence → personal landmark → season → offered bounds → convergence
→ defer (`chronology.md` §6). Rungs that need a landmark are skipped when the
person has not supplied one; the rung actually chosen for an unknown is
`timeline_interaction.choose_probe`'s output and it is substituted into the
leaf as `{probe}`.

**"I'll find out" is an ordinary answer** (v196). It files nothing and is
remembered nowhere: the unknown simply stays outstanding, keeps its star and
its leverage, and is offered again whenever the ordering says it is worth
offering. The courtesy survives as the ladder's last rung and as the
`timeline_gates.accepts_defer` lint — a person who says they will find out is
received, never pressed.

**Both accounts survive a contradiction.** Oral history treats the
disagreement itself as data (Portelli). `chronology.reconcile` scores claims
and returns `{best_supported, alternates}` — and never drops one (owner
ruling 3).

**One gap, one conversation** (v234, lifehug-platform#664). A temporal
contradiction, an identity the resolver could not place, and a precision gap
are all things the system is confused about and only the person can settle —
and settling one IS dating work. So Play on any of them opens THIS
interaction's fourth stage, `work_item`, rather than a seventh child of
Conversation: the Play kind and the stage name are the same word
(`mirror_work.PLAY_TARGET_KIND` == `timeline_interaction.WORK_ITEM_STAGE`), so
one gap opens one conversation no matter which surface the person saw it on
(plan §2.3). The stage reuses everything: the target and its bounded evidence
are `mirror_work.play_target`'s, the output is the same optional `placed`
field with no new key beside it, further facts in the same breath are heard by
the general listener as in any conversation, and a settled contradiction files
through `mirror_work.resolve_mirror_item` — the person's words become a source
and the reading they did not choose is retired by a correction that deletes
nothing. "I don't know" writes nothing at all and the item stays (§2.5).

**Passive users are untouched.** The daily single question keeps working
exactly as it did; this Interaction runs only when an unknown is Played.
Mechanically: `TurnShape.timeline_stage` defaults to `None` and the output
contract is then byte-identical to v194 (owner ruling 7).

**Platform twin.** A host REPLAYs this package and reads exactly these —
nothing else is a contract (the shared shape: `interactions/README.md`
§ "The child-interaction paradigm"):

| What | Where |
|---|---|
| The date record | `chronology.DateRecord`; `chronology.GRANULARITIES\|CONFIDENCES\|BASES` |
| Serialize / parse / render | `chronology.to_edtf`, `chronology.parse_edtf`, `chronology.from_dict`, `chronology.display_date` |
| The arithmetic | `chronology.from_age`, `chronology.from_anchor`, `chronology.intersect`, `chronology.widen_for_elapsed`, `chronology.reconcile` |
| The `{timeline_stage}` this turn is in | `timeline_interaction.timeline_stage_for_session(session, user_leaving=…, placement_settled=…, no_new_bound_streak=…, work_item=…)`; `timeline_interaction.VALID_TIMELINE_STAGES` |
| The work-item stage's target | `timeline_interaction.work_item_target(play_target_or_item)` — `None` refuses, never raises; `timeline_interaction.WORK_ITEM_STAGE`, `WORK_ITEM_KINDS` |
| Its probe and its `{work_item}` block | `timeline_interaction.work_item_probe(target, anchors=…)`, `timeline_interaction.render_work_item(target)`, `timeline_interaction.work_item_known_years(target)`; host side `conversation_delivery._work_item_context_block` |
| What a work-item answer settles | `timeline_interaction.work_item_retire_ids(target, placed)` → `timeline_interaction.work_item_resolution(target, placed, resolution_text=…)`, whose kwargs go straight to `mirror_work.resolve_mirror_item` (`mirror.resolve_actionable_item` for the bound single vault). `None` means write nothing |
| The person's landmarks and the `{anchors}` block | `timeline_interaction.anchors_for_person(...)`, `timeline_interaction.render_anchors(anchors)` |
| The next question to ask | `timeline_interaction.choose_probe(unknown, anchors=…, precision_so_far=…, asked_steps=…)`; `timeline_interaction.PLAYBOOK_STEPS` |
| `{precision_so_far}` | `timeline_interaction.precision_so_far(session)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["placed"]`, enabled by `TurnShape(timeline_stage=…)` |
| Closed validation of that field | `timeline_interaction.validate_placed(value, anchors=…)` |
| The seven timeline lints | `timeline_interaction.lint_timeline_reply(text, stage=…, probe_step=…, known_years=…)`; `timeline_interaction.TIMELINE_LINT_CLASSES`. The seventh, `never_proposes_a_date`, is SHARED with the landmarks lane from one definition (`timeline_interaction.proposes_a_date`) |
| Filing an accepted placement | `timeline_interaction.place_invocation(placed, source=…, description=…, period=…, placement_key=…)` → a `PlaceInvocation(argv, stdin_text)`; the host runs BOTH halves (`timeline-place` reads the description on stdin and exits 1 without it — lifehug#223). `placement_key` is the moment's own `timeline.placement_key`, carried on the unknown row — pass it and identity is mint/join-symmetric; omit it and the CLI derives the key from source + description as it always has (lifehug#228) |
| The unknowns to Play | `timeline.unknowns(data)`, `timeline.UNKNOWN_KINDS`, `timeline.keystones(data)`, `timeline.KEYSTONE_CAP` |
| The two ways a keystone is asked | `timeline_interaction.whisper_from_keystone`, `timeline_interaction.mint_keystone_question` / `insert_keystone_question` / `timeline_probe_index` |
| This turn's timeline item | `timeline_interaction.timeline_item_for_session`, `timeline_interaction.timeline_asks_so_far`, `conversation_delivery.timeline_item_for_turn` |
| The reply to a timeline ask | `timeline_interaction.answer_timeline_probe(entry, reply, anchors=…)` |
| The filing beat's one sentence (v207) | `cross_dating.gain_sentence_for_record(record, timeline_payload)` → `cross_dating.render_filing_gain(sentence)` for the `{filing_gain}` slot; the moment clause is `cross_dating.moment_clause`, the SAME definition `reading_room.placement_gain_sentence` says. **Platform wiring:** the engine fills the kwarg AFTER it files the turn's record, from the timeline payload it already holds, and passes `""` (or omits it) on every other turn — the substitution is additive and the prompt is byte-identical without it. |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{timeline_stage}`, `{unknown_label}`, `{probe}`, `{anchors}`, `{precision_so_far}`, `{filing_gain}`, `{work_item}` |
| The read-only plan verb | `lifehug.py arc-plan-target --timeline [--era <slug>] [--json]` |
| The write verb | `lifehug.py timeline-place <source> --period <slug> [--date <edtf>] [--basis <basis>] [--anchor <key>]… [--placement-key <12-hex>]` |

The FILING of a placement is entirely host-side: the package names the date,
the host writes it.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py timeline-evals --json
```

See `docs/pr-specs/timeline-chronology.md` (v195) and
[ADR 0024](../../docs/adr/0024-chronology-with-basis.md).
