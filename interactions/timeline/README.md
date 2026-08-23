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

**"I'll find out" is a real state.** A deferral is neither a decline nor a
debt: `state/timeline_deferred.json` records it, the unknown goes quiet for
`DEFERRED_QUIET_DAYS`, it keeps its star and its leverage, and it is never
counted as outstanding (owner ruling 5).

**Both accounts survive a contradiction.** Oral history treats the
disagreement itself as data (Portelli). `chronology.reconcile` scores claims
and returns `{best_supported, alternates}` — and never drops one (owner
ruling 3).

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
| The `{timeline_stage}` this turn is in | `timeline_interaction.timeline_stage_for_session(session, user_leaving=…, placement_settled=…, no_new_bound_streak=…)` |
| The person's landmarks and the `{anchors}` block | `timeline_interaction.anchors_for_person(...)`, `timeline_interaction.render_anchors(anchors)` |
| The next question to ask | `timeline_interaction.choose_probe(unknown, anchors=…, precision_so_far=…, asked_steps=…)`; `timeline_interaction.PLAYBOOK_STEPS` |
| `{precision_so_far}` | `timeline_interaction.precision_so_far(session)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["placed"]`, enabled by `TurnShape(timeline_stage=…)` |
| Closed validation of that field | `timeline_interaction.validate_placed(value, anchors=…)` |
| The five timeline lints | `timeline_interaction.lint_timeline_reply(text, stage=…, probe_step=…, known_years=…)`; `timeline_interaction.TIMELINE_LINT_CLASSES` |
| Filing an accepted placement | `timeline_interaction.place_invocation(placed, source=…, description=…, period=…)` |
| The unknowns to Play | `timeline.unknowns(data)`, `timeline.UNKNOWN_KINDS`, `timeline.keystones(data)`, `timeline.KEYSTONE_CAP` |
| The deferred memory | `timeline.defer_unknown`, `timeline.is_deferred`, `timeline.DEFERRED_QUIET_DAYS` |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{timeline_stage}`, `{unknown_label}`, `{probe}`, `{anchors}`, `{precision_so_far}` |
| The read-only plan verb | `lifehug.py arc-plan-target --timeline [--era <slug>] [--json]` |
| The write verb | `lifehug.py timeline-place <source> --period <slug> [--date <edtf>] [--basis <basis>] [--anchor <key>]…` |

The FILING of a placement is entirely host-side: the package names the date,
the host writes it.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py timeline-evals --json
```

See `docs/pr-specs/timeline-chronology.md` (v195) and
[ADR 0024](../../docs/adr/0024-chronology-with-basis.md).
