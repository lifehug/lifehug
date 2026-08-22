# Contract: arc-walk-interaction

## Why

Platform issue #570 §3 ("Play everywhere") names the one genuinely new goal in
the Play-target design: **work through a set of open questions, casually, as
many as feels natural, resumable.** Pressing Play on a focus, a chapter, or a
book is a commitment to answer a lot in one sitting — and today the package has
no object that can express that. It has a weekly queue, and it has one arc card
per queued question. It has never had a plan that spans several questions.

Three facts make this an OSS change rather than a platform one.

1. **There is no multi-question plan object anywhere.** `arc_planner.plan()`
   writes `state/arc_cards.json` with exactly one card per queued question
   (`plan_deterministic`, `system/arc_planner.py:673`): an opening plus 2–4
   typed intents, expiring with the queue. A focus with eleven open questions
   gets eleven unrelated cards and no order, no agenda, and no idea that they
   belong to one conversation. The owner's Foundation Play is "find arcs
   between the questions", which is a plan across cards, not a card.
2. **The conversation has no way to be told what it is walking.** ADR 0016's
   `asking_supply` block offers the top-K held bank questions as *advisory*
   context inside an ordinary chat; the model may ask one when invited. That
   is a whisper, deliberately. An episode is the opposite posture: the person
   has said "let's do this", the order is pre-computed, and the opener
   ANNOUNCES it. Nothing in the parent Conversation can announce an agenda,
   and nothing should — that is a second goal, which by the child-interaction
   paradigm (`interactions/README.md`) is a second child.
3. **Nothing names which question an answer answered.** The structured turn
   output carries `held_question_id` — the qid the model *asked* — and the
   engine stamps it onto the ASSISTANT turn (`conversation_delivery.py:1525`,
   `"question_id": followup_id or question_id`). There is no field for the qid
   the USER's answer actually addressed, so a story that answers question
   three while question one was on the table has nowhere to say so.

This PR is the smallest change that fixes all three: one new child
interaction, one pure module, exactly one additive turn-output field, seven
lints, nine goldens, two read-only CLI verbs, and one ADR.

## Rulings (owner, 2026-08-22 — verbatim, binding)

1. **Foundation Play on a focus / chapter / book** "starts a conversation that
   will start to answer every open question… I'm committing to answering a
   lot… find arcs between the questions to have a casual conversation… as many
   as possible… moments where it can leave and come back later… not feel like
   they're missing something if they leave… press Play again and answer the
   rest… see all those additions in chats."
2. **Pre-generate the order, let the model deviate**: the plan is a map, not a
   script. The opener ANNOUNCES the agenda ("today: Etherfuse and purpose —
   three things I'd love to hear about").
3. **Episodes, not marathons**: one session walks a slice (size by tier/time,
   ~4–8); closes warmly with what was covered and what waits — no checklist,
   no streak, never "unfinished".
4. **Resume = a new episode of a plan RECOMPUTED from the bank at Play**
   (answered questions fall out; nothing persisted except the existing
   declined memory).
5. **Each answer files to the question it actually answered**: the question on
   the table = the qid the previous assistant turn asked; one additive output
   field names the plan question this answer addressed (default: the one
   asked). Primary-only filing when an answer covers two.
6. **Passive users are untouched**: the daily single question keeps working
   exactly as today; this interaction only runs when a target with N questions
   is Played (by a person now; by the scheduler later).

## Binding facts

As of `origin/main` `83c2ae5`, `system/version.json` version **192**,
released 2026-08-22.

**The precedent this PR copies, line for line.**

- `docs/pr-specs/question-candidate-placement-aside.md` (v188),
  `docs/pr-specs/focus-onboarding-context.md` (v189),
  `docs/pr-specs/entity-identity-context.md` (v190) — the contract shape, the
  "exactly one additive output field" discipline, the two-layer validation
  split, the transcript-derived stage, the lint table, the golden list, the
  platform-twin table.
- `interactions/README.md` § "The child-interaction paradigm" — the six-point
  shape this child repeats, and the four-children table it completes.
- `system/focus_candidate.py:500` `focus_stage_for_session`, `:534`
  `validate_focus_setup`, `:660` `lint_focus_setup_reply`, `:77`
  `VALID_FOCUS_STAGES`.
- `system/entity_candidate.py` `entity_stage_for_session` /
  `validate_entity_setup` / `lint_entity_setup_reply` /
  `VALID_ENTITY_STAGES`.
- `system/conversation_delivery.py:151` `TurnShape` (`:177` `placement_stage`,
  `:186` `focus_stage`, `:195` `entity_stage` — all defaulting to `None`),
  `:300` `_output_contract_block`, `:418` `parse_turn_output`, `:503`
  `_parse_focus_setup`, `:560` `_parse_entity_setup` (the structural layer
  that owns no vocabulary and never raises).
- `system/entity_candidate_evals.py:16–58` (a SECOND, independent golden pair
  beside the frozen one), `:85–250` (loaders, fixture validation, scorer),
  `:395–420` (one `check_gates` call over both prefixes).

**The planner and the arcs as they stand.**

- `system/question_planner.py:553` `enriched_pending_questions` — the ONE
  ranking authority: per-question `weight` after focus weighting, quality
  multiplier, rumination cooldown ×0.25, the Aron escalation gate ×0.05, and
  the love-map staleness boost; sorted `(objective is None, category_ratio,
  group=="focus", qid_key)`.
- `system/question_planner.py:672` `build_queue` — the weekly aggregation. Its
  `weighted_pick` weight expression is
  `max(weight, 0.0001) * (policy["objective_boost"] if objective else 1.0)`
  and its `eligible(..., enforce_arc=True)` refuses a question whose category
  equals the current streak once `streak_count >= arc_max`. `build_queue` is
  a *sampler* (`rng.choices`, seeded per ISO week); an episode plan must be an
  ORDER, so this PR reuses the same weight expression and the same streak cap
  deterministically rather than re-deriving either.
- `system/question_planner.py:70` `DEFAULT_LANE_POLICY` (`objective_boost`),
  `:164` `qid_key`, `:368` `resolve_roadmap`, `:393` `build_focus_index`.
- `system/arc_planner.py:673` `plan_deterministic` — one card per queued
  question: `{question_id, opening, opening_receipts, intents, planned_at,
  planner}`; `:86` `INTENT_KINDS = conversation.ARC_INTENT_KINDS`, `:92`
  `CONSUMED_GAP_KINDS`, `:1162` `live_card` (the liveness rule this PR does
  NOT duplicate).
- `system/conversation.py:833` `ARC_INTENT_KINDS` (the closed six), `:537`
  `load_arc_cards`, `:716` `_declined_question_ids`, `:811`
  `_assemble_asking_supply_block`, `:788` `asking_supply_selection`.
- `system/conversation_delivery.py:943` `_detect_declined_held_question` —
  the deterministic decline rule, keyed on the PRIOR assistant turn's
  `asked_from_supply` + `question_id`.
- `system/roadmap.py:376` `focus_fill`, `:417` `FOCUS_TYPES`, `TIER_TARGETS`,
  and the focus record's `tier` ∈ `basic|standard|extreme` (`ask.py:69`
  `tier_for_size`).
- `system/lifehug.py:2158` — `planner-queue --arc-max` default `2`.

**The "asked qid" concept already exists; this PR adds no second one.**

`held_question_id` is what the MODEL returns when it asked a question from
`ASKING_SUPPLY`. The ENGINE writes that same qid onto the assistant turn as
`turn["question_id"]` (`conversation_delivery.py:1519–1528`, the `lifehug_turn`
literal, plus `asked_from_supply: true` when it was a held pick). The hosted
platform's `stamped_question_id` is its own name for that same assistant-turn
field. **All three are one concept**: *the qid the previous assistant turn
asked*. This PR names it once, as a pure reader —
`arc_walk.asked_question_id(turn)` — and adds no new field, no new session
key, and no new lifecycle state.

**Handbook / manifest discipline.**

- `tests/test_handbook_parity.py` `HandbookParityTests` — every quoted number
  under `docs/` carries a `parity:` HTML comment naming `module.CONSTANT` and
  its value, and is asserted against the live constant. (Deliberately not
  spelled out literally here: the scanner reads every markdown file under
  `docs/`, this contract included.)
- `EmbedParityTests` — each seated-interaction handbook page embeds its
  `prompt/behavior.md` byte-for-byte; the expected map gains the arc-walk row
  and the floor rises 6 → 7.
- `tests/test_entity_candidate.py:208` / `tests/test_focus_candidate.py:208`
  digest ONLY `interactions/conversation/` and
  `interactions/question_candidate/`; both explicitly permit new sibling
  packages. **This PR touches neither, so neither digest moves.**
- `system/interaction_registry.py:19` `REQUIRED_FILES` / `:37`
  `COMPOSABLE_FILES` — a child's `composition.append | composition.leaf` must
  equal `COMPOSABLE_FILES` exactly, and every required asset must exist.
- `system/version.json` `framework_files` must list every new file under
  `interactions/arc_walk/**` plus `system/arc_walk.py`,
  `system/arc_walk_evals.py`.

## Scope

**In:** the `arc_walk` child interaction (definition + registry row); the pure
`system/arc_walk.py` (plan builder, stage, question-on-the-table, closed
validation, seven lints, episode sizing); the one additive
`answered_question_id` turn-output field (structural parse gated on
`TurnShape(arc_stage=…)`, closed validation in `arc_walk`); the
`arc-plan-target` and `arc-walk-evals` CLI verbs; nine goldens and the
`arc_walk_gates.*` harness; ADR 0023; the ADR 0018 fourth-instance row; the
interactions README fourth-child row; the handbook loop-page note, glossary
entries, and the arc-walk interaction page; the version bump.

**Out (deliberate, named):**

- **Persisting the plan.** Ruling 4 makes the plan a recomputation, not a
  record. No `state/arc_plans.json`, no new key in `state/arc_cards.json`, no
  vault-contract path. The only durable memory an episode leans on is the one
  that already exists: `session["declined_question_ids"]` (ADR 0016).
- **Writing a focus-level card into `state/arc_cards.json`.** Issue #570's
  first noted gap suggests extending `arc-plan` with a focus-level weekly
  card. That is a WRITER change to the weekly loop with its own expiry,
  validation, and merge semantics; this PR computes the same order on demand
  at Play, from the bank, which is what ruling 4 requires anyway. If the
  weekly loop later wants to pre-warm it, `build_arc_plan` is the function it
  will call. Recorded here so the deferral is visible, not silent.
- **Stamping queue-item `status` when a Play answers it.** Issue #570's second
  noted gap. That is a `question_planner` writer change and a `/queue` display
  question; nothing in this PR reads or writes queue status.
- **Multi-qid FILING.** The package names which question an answer answered
  (`answered_question_id`); the platform's `turn_filing.py` is what routes it
  to a file. `run_post_answer_turn`'s own filing path is unchanged by this PR
  — the field is recorded and validated, not consumed by a new OSS writer.
- **Any change to ordinary Conversation prompt bytes**, to the parent's
  behavior/identity/examples, to `asking_supply`, to the arc planner, to
  `build_queue`, or to the composition policy.
- **A per-session question cap.** ADR 0016 deliberately has none ("as many as
  belong in a great conversation"); the episode size bounds the AGENDA, never
  the conversation.

## Design

### A. The child: `interactions/arc_walk/`

`extends: conversation`, `extends.version: 1.0.0`, `modes: walk`.
`composition.append` = `prompt/identity.md|prompt/behavior.md|
prompt/examples.md|router/router.md|router/deflection.md`;
`composition.leaf` = `prompt/turn-instructions.md|context/manifest.md`. The
union is exactly `COMPOSABLE_FILES`, so `audit_interaction_package("arc_walk")`
returns `[]`.

**A1. `prompt/turn-instructions.md` is the stage-keyed leaf.** Placeholders,
substituted by the caller and nothing else:

| placeholder | value |
|---|---|
| `{arc_stage}` | `open` \| `walk` \| `close` — `arc_walk.arc_stage_for_session` |
| `{agenda}` | the episode's question texts, numbered, one per line — `arc_walk.render_agenda(plan)` |
| `{focus_label}` | the target's label — `plan["focus_label"]` |
| `{episode_size}` | `plan["episode_size"]` |
| `{answered_k}` / `{plan_n}` | `plan["answered_k"]` / `plan["plan_n"]` — the bank fact, for the model's own sense of scale. **Never spoken.** |

- `open` — announce the agenda ONCE, warmly and in one breath: what today is
  about and roughly how much ("Today I'd love to hear about {focus_label} —
  three things."). Then ask the FIRST agenda question. Never a numbered list
  read aloud, never a count of what remains.
- `walk` — receive the answer the way any Conversation turn would, then bridge
  naturally to the next agenda question. Follow a tangent when the person
  takes one — the plan is a map, not a script — and come back to it later, or
  don't. When they decline one, skip it and move on without comment. At most
  ONE question per reply. Never restate the agenda.
- `close` — summarize warmly what was covered and say the rest waits whenever
  they like. No question, no count, no "unfinished".

`answered_question_id` is null unless this turn's user message answered a
DIFFERENT agenda question than the one on the table; then it is that question's
exact id.

**A2. Router deflection → close.** `router/deflection.md` adds one rule to the
inherited deflection anatomy: when the latest inbound says they are leaving
("I need to go", "let's pick this up later"), the interaction does not deflect
and does not ask — it goes to `close`. The router extension classifies the
leaving signal; `arc_stage_for_session(..., user_leaving=True)` is how the
caller expresses it. Deterministically: `user_leaving` forces `close`
regardless of episode progress.

**A3. Identity / behavior / examples** append to the parent's. Behavior adds
five numbered rules inside this child's own numbering (the parent's numbering
is frozen): announce once · one question per reply · the plan is a map ·
never count · close warm. `prompt/behavior.md` is the file the handbook page
embeds byte-for-byte.

### B. `system/arc_walk.py` — the pure module

No writes, no model calls, no lifecycle. It inherits exactly the guarded
optional reads `question_planner.enriched_pending_questions` already performs
(answer dates, quality profile), the same way
`conversation.asking_supply_selection` does; every one degrades to a default
rather than raising.

**B1. The target.**

```python
ARC_TARGET_KINDS = ("focus", "chapter", "book", "category", "queue")

normalize_target(value) -> {"kind": str, "ref": str, "label": str,
                            "categories": tuple[str, ...]}
```

`kind` must be in `ARC_TARGET_KINDS` (exact, no case-fold); `categories` are
the bank category letters the target covers, deduplicated, order-preserved.
An unknown kind, a missing ref, or an empty category set raises
`ArcWalkError` — a target nobody can enumerate is a caller bug, not something
to degrade around (the `opening_question` precedent).

**B2. The plan.**

```python
build_arc_plan(target, *, questions, categories, coverage, tier,
               episode_size=None, focus_index=None, objectives=(),
               cards=(), declined_question_ids=()) -> dict
```

returns

```python
{"target": {kind, ref, label, categories},
 "focus_label": str,
 "questions": [{"id": str, "text": str, "category": str, "intent": str | None}],
 "episode_size": int,
 "plan_n": int,
 "answered_k": int}
```

- `questions` are the target's OPEN questions in plan order (ruling 4:
  answered ones fall out at Play).
- **`plan_n` is every question in the target's categories, answered or not;
  `answered_k` is how many of those are already answered.** "k of N" is a bank
  fact (issue #570 §3), so `len(plan["questions"]) == plan_n - answered_k`
  holds by construction and is a required test.
- `episode_size` is `episode_size_for(tier, override=episode_size)`.

**Ordering REUSES the planner, and re-derives nothing.** Rows come from
`question_planner.enriched_pending_questions(questions, categories, coverage,
list(objectives), focus_index)` — the one ranking authority — restricted to the
target's categories and with `declined_question_ids` removed. They are then
ordered by `build_queue`'s own weight expression, made deterministic:

```python
_plan_weight(row, policy) = max(float(row["weight"]), 0.0001) * (
    policy["objective_boost"] if row.get("objective") else 1.0)
```

with `policy = question_planner.DEFAULT_LANE_POLICY` (imported, never
re-typed), sorted by `(-_plan_weight, row["category_ratio"],
question_planner.qid_key(row["id"]))`. `build_queue` feeds the identical
expression to `rng.choices`; an episode needs an ORDER, so the same weights
sort instead of sample. A test asserts the expression matches `build_queue`'s
literal by AST, so a policy change fails the build rather than drifting.

**The `arc_max` streak cap is `build_queue`'s, applied as a re-order.** Walking
the weight-sorted list greedily, a question whose category equals the current
streak category is DEFERRED once `streak_count >= arc_max` and the next
eligible one is taken instead; when nothing else is eligible the deferred one
is taken anyway (`build_queue`'s own last-resort). `DEFAULT_ARC_MAX = 2`,
AST-pinned against `lifehug.py`'s `planner-queue --arc-max` default so the two
loops cannot drift.

**Intents come from the arc cards when cards exist.** `cards` is the card list
a caller read from `state/arc_cards.json` (`conversation.load_arc_cards()
["cards"]`). For a planned question with a card, `intent` is
`intent_note(card)`: the card's FIRST intent object rendered short — its
`note`, else its `slot`, else its `kind` — where `kind` must be in
`conversation.ARC_INTENT_KINDS` (imported, never re-listed). No card, no
intents, or an unknown kind → `None`. **Card LIVENESS is not re-derived here**:
`arc_planner.live_card` owns that rule and the caller applies it; a stale card
contributes a stale intent, which is a bridge suggestion, not a fact.

**B3. Episode size.**

```python
EPISODE_SIZES = {"basic": 4, "standard": 6, "extreme": 8}
DEFAULT_EPISODE_SIZE = 6
MIN_EPISODE_SIZE, MAX_EPISODE_SIZE = 1, 12

episode_size_for(tier, *, override=None) -> int
```

An unknown or blank tier falls back to `DEFAULT_EPISODE_SIZE` (a focus whose
tier nobody set is still walkable). `override` wins when it is an `int` inside
`[MIN_EPISODE_SIZE, MAX_EPISODE_SIZE]`; anything else is ignored rather than
raising. The three numbers are ALSO knobs in
`interactions/arc_walk/interaction.yaml` (`knob.episode_size_basic` …), read
through `interaction_registry.load_interaction_manifest("arc_walk")` in a
try/except with the module constants as the fallback — the
`knob.asking_supply_top_k` pattern (`conversation.asking_supply_selection`)
exactly. A required test pins manifest == constants, so tuning the knob and
tuning the constant are the same edit.

`_session_capped` (25 exchanges, `knob.conversation_turn_cap_exchanges`) is
untouched and still the hard ceiling; `MAX_EPISODE_SIZE = 12` sits well under
it, so the episode always closes on its own terms rather than being cut off
(ruling 3, and issue #570's risk 2).

**B4. Stage.**

```python
VALID_ARC_STAGES = frozenset({"open", "walk", "close"})

arc_stage_for_session(session, plan, *, user_leaving=False) -> str
```

Derived from the transcript alone — no new session field, no lifecycle status,
the `focus_stage_for_session` precedent:

- `user_leaving` → `"close"`, always, first (§A2).
- no assistant (`role == "lifehug"`) turn yet → `"open"`.
- `len(answered_plan_question_ids(session, plan)) >= plan["episode_size"]` →
  `"close"`.
- otherwise `"walk"`.

`answered_plan_question_ids(session, plan) -> tuple[str, ...]` is the distinct,
in-order plan qids stamped on this session's USER turns — the episode's own
progress, which is a transcript fact, not a stored counter.

**B5. The question on the table.**

```python
asked_question_id(turn) -> str | None
question_on_the_table(session, plan) -> str | None
```

`asked_question_id` is the ONE naming of the existing concept (Binding facts):
a `role == "lifehug"` turn's `question_id`, trimmed, else `None`.
`question_on_the_table` returns the LAST assistant turn's asked qid when it is
a plan question, else the first plan question not yet answered in this session,
else `None` (an exhausted episode has nothing on the table).

**B6. The closed validator.**

```python
validate_answered_question_id(value, *, plan) -> str | None
```

`value` is the structural layer's own output (a trimmed non-empty string ≤ 16
characters, or `None`) or any other untrusted shape. Exact membership in the
plan's OPEN question ids — no case-fold, no prefix match, no chain-root
walking. A qid the plan does not carry drops to `None`: the package refuses to
file an answer against a question this episode never put on the table. This
is `validate_placement`'s closed-roster discipline applied to a plan.

**Primary only (ruling 5, and issue #570 risk 1).** The field is one qid, not
a list. An answer that covers two questions names the primary; the compiler
already cross-links by content. A caller that wants the default — "the one
that was asked" — reads `question_on_the_table`; `answered_question_id` only
ever OVERRIDES it.

### C. The `answered_question_id` field

Exactly one new key in the structured turn output, additive and optional:

```json
"answered_question_id": "G12" | null
```

Two validation layers, the same split as `placement` (v188), `focus_setup`
(v189) and `entity_setup` (v190):

1. **Structural** — `conversation_delivery._parse_answered_question_id`, called
   from `parse_turn_output`. A string, `.strip()`ed, non-empty, at most
   `_ANSWERED_QUESTION_ID_MAX_CHARS` (16) characters. Anything else — missing,
   `null`, a number, an object, a 17-character value — degrades to `None`.
   Never raises. Owns no plan and performs no membership check.
2. **Closed** — `arc_walk.validate_answered_question_id(value, *, plan)`
   (§B6).

**`TurnShape` gains `arc_stage: str | None = None`** — the fourth gate, in
order after `entity_stage`. `_output_contract_block` appends the
`answered_question_id` line and its note ONLY when `arc_stage is not None`;
with the gate `None` the appendix is byte-identical to pre-v193 output
(required test — ruling 6's mechanical form: the passive daily question's
prompt does not move by one byte).

**Engine stamping**: unchanged. The assistant turn keeps carrying
`question_id` (`followup_id or question_id`) and `asked_from_supply`;
`arc_walk.asked_question_id` reads it. No second concept.

### D. Lints

New gate class `arc_walk_gates.*` in `interactions/arc_walk/evals/lints.yaml`,
produced by `arc_walk.lint_arc_reply(text, *, stage, agenda_announced=False)`,
whose findings share `conversation_lints.lint_turn`'s shape
(`{"lint", "detail", "span"}`). An unrecognized stage is treated as `walk`
(fail toward the strictest ordinary rule: no agenda, no counters).

| lint id | rule | applies on |
|---|---|---|
| `arc_walk.agenda_announced_once` | the opener announces the agenda exactly once, in exactly one sentence | `open` |
| `arc_walk.agenda_never_repeated` | no agenda announcement at all | `walk`, `close`, and any `open` turn where `agenda_announced` is already true |
| `arc_walk.one_question_per_reply` | at most one `?` | every turn |
| `arc_walk.no_counters` | no "3 of 6", "two more", "questions left", "you still have" | every turn |
| `arc_walk.no_mechanism_talk` | no "the plan", "the queue", "your question bank", "I'll file this", "the system will", "arc" | every turn |
| `arc_walk.close_summarizes` | the close names what was covered AND says the rest waits, and asks nothing | `close` |
| `arc_walk.no_pressure` | no "unfinished", "you didn't", "still need to", "finish", "streak", "fell behind" | every turn |

The agenda's invariant anchor — what every agenda lint locates — is a sentence
pairing a **today** cue (`today`, `this time`) with a **hearing** cue
(`love to hear`, `like to hear`, `want to hear`, `talk about`, `go through`,
`get into`), in either order. The model varies the connective tissue, never
the move (ruling 2). The close's anchors are a **covered** cue (`we covered`,
`we talked about`, `we got`, `we went through`, `what we did`) and a **waits**
cue (`whenever you like`, `will keep`, `waits`, `no rush`, `when you want`) —
both required, because a close that says what happened but not that the rest
waits is exactly the "missing something if they leave" failure ruling 1
forbids.

An `arc_walk` lint failure is a lint failure exactly as an inherited
Conversation lint failure is; the documented degradation is one retry WITHOUT
the agenda sentence before degrading further (the recipe v188/v189/v190 all
prescribe).

### E. The CLI

**`arc-plan-target`** — read-only, no writes, no model:

```
lifehug.py arc-plan-target (--focus ID | --category LETTER | --book FOCUS_ID
                            | --chapter LETTER | --queue)
                           [--episode-size N] [--json]
```

Loads the bank and roadmap (`question_planner.load_question_state`,
`resolve_roadmap`, `build_focus_index`), resolves the target's categories and
tier, reads `conversation.load_arc_cards()["cards"]` for intents, and prints
the plan: the target line, `k of N` answered, and the numbered episode agenda
(or the whole plan JSON under `--json`). It is registered in
`READ_ONLY_COMMANDS` — it takes no writer lock, exactly like `arc-card`.

**`arc-walk-evals`** — `[--live] [--json]`, the seat gate, in
`READ_ONLY_COMMANDS` beside the other three `*-candidate-evals`.

### F. Goldens and the harness

`system/arc_walk_evals.py`, modeled on `entity_candidate_evals.py`'s identity
pair: `goldens/arc_fixtures.json` + `goldens/arc_sample_predictions.json`,
`load_gates` reading the `arc_walk_gates.` prefix, ONE `check_gates` call.
Fixture shape:

```json
{"fixture_id": "...",
 "target": {"label": "...", "plan_question_ids": ["G12", "G14"]},
 "turns": [{"stage": "walk", "agenda_announced": true, "user_leaving": false,
            "expected_answered_question_id": "G14"}]}
```

Predictions carry `{"message", "answered_question_id"}` per turn. Each turn is
linted at its stage and its raw `answered_question_id` is passed through BOTH
layers (`conversation_delivery._parse_answered_question_id` then
`arc_walk.validate_answered_question_id`) exactly as a real caller would, and
compared with the fixture's expectation.

Nine required goldens:

1. `arc-open-announces-agenda-once` — the agenda in one sentence, then the
   first question; no counters.
2. `arc-walk-bridges-to-next-question` — receives the answer, bridges, asks
   the next plan question; names `answered_question_id`.
3. `arc-walk-user-tangent-keeps-plan` — the person goes sideways; the reply
   follows them, asks about the tangent, and re-states no agenda.
4. `arc-walk-decline-skips` — "I'd rather not" → the reply moves on without
   comment, no pressure, `answered_question_id` null.
5. `arc-close-summarizes-without-counters` — covered + waits, no `?`, no
   number.
6. `arc-walk-two-questions-in-one-answer-files-primary` — the answer covers
   two; exactly one qid is named (ruling 5).
7. `arc-walk-passive-single-question-is-byte-identical` — an ordinary daily
   turn with no `arc_stage`: `answered_question_id` null, appendix byte-
   identical (ruling 6).
8. `arc-close-user-signals-leaving` — "I need to go" mid-episode: `close`,
   warm, nothing about what is unfinished.
9. `arc-walk-unknown-question-id-rejected` — a reply naming a qid the plan
   does not carry normalizes to `None` without failing the turn.

## Required tests

`python3 -m unittest discover -s tests` (and `python3 -m pytest -q`) green.

**`tests/test_arc_walk.py`** (new — one file for the whole contract, including
the delivery-engine layer, so the v193 surface reads as one thing)

- `test_output_contract_block_byte_identical_without_arc_stage` — a
  `TurnShape` with no `arc_stage` produces the exact pre-v193 appendix.
- `test_answered_question_id_line_and_note_present_when_staged` — all three
  stages.
- `test_answered_question_id_absent_is_none` /
  `test_answered_question_id_malformed_degrades_never_raises` — non-string,
  empty, whitespace, 17 chars, an object, a list, a number → `None`.
- `test_all_four_additive_fields_coexist_in_a_stable_order` — placement,
  focus_setup, entity_setup, answered_question_id, rolling_summary.
- `test_normalize_target_closed_kinds_and_raises_on_unusable`.
- `test_build_arc_plan_orders_by_planner_weight` — a higher-weight question
  precedes a lower-weight one regardless of bank order.
- `test_build_arc_plan_weight_expression_matches_build_queue` — the AST pin.
- `test_default_arc_max_matches_planner_queue_cli_default` — the AST pin.
- `test_build_arc_plan_applies_the_arc_max_streak_cap` — three same-category
  questions do not appear consecutively; and the last-resort case still emits
  all of them.
- `test_build_arc_plan_drops_answered_and_declined`.
- `test_plan_counts_are_bank_facts` — `len(questions) == plan_n - answered_k`.
- `test_build_arc_plan_takes_intents_from_cards_and_never_invents` — a card's
  first intent note becomes `intent`; an unknown `kind` and a missing card both
  give `None`; `conversation.ARC_INTENT_KINDS` is the vocabulary (a monkeypatch
  changes the result — the pin that no second vocabulary exists).
- `test_episode_size_by_tier_and_override_bounds` + unknown tier falls back.
- `test_episode_manifest_knobs_match_the_module_constants`.
- `test_arc_stage_for_session_derived_from_transcript` — open/walk/close and
  `user_leaving` forcing close from any progress.
- `test_answered_plan_question_ids_are_distinct_and_in_order`.
- `test_asked_question_id_reads_the_existing_assistant_turn_field` — a user
  turn's `question_id` is NOT an asked qid.
- `test_question_on_the_table_prefers_the_asked_qid_then_the_first_unanswered`.
- `test_validate_answered_question_id_is_exact_plan_membership` — off-plan,
  case-variant, chain-root parent, and answered-question ids all → `None`.
- `test_answered_question_id_keys_match_the_structural_layer`.
- `test_render_agenda_is_the_episode_slice_numbered`.
- `test_lint_arc_reply_*` — one per §D row, a passing and a failing reply each;
  unknown stage fails toward `walk`; findings share the inherited shape.
- `test_leaf_is_stage_keyed_and_placeholder_bearing` — the leaf carries all
  five placeholders.
- `test_registry_audit_is_clean_and_lineage_is_conversation_arc_walk`.
- `test_conversation_and_question_candidate_packages_are_byte_identical` — the
  two digests this PR must not move.
- `arc-plan-target`: resolves a focus target from a synthetic vault, prints
  `k of N`, `--json` emits the plan dict, and writes NOTHING (the vault is
  byte-identical across the call).

**`tests/test_arc_walk_evals.py`** — the nine goldens load, validate, score,
and gate; a deliberately-bad prediction fails its own class only.

**Harness** — `python3 system/lifehug.py arc-walk-evals` passes;
`question-candidate-evals`, `focus-candidate-evals`, `entity-candidate-evals`
and `conversation-evals` are untouched and pass.

## Version bump

`system/version.json`: **192 → 193**, `released` set to the merge date, a full
changelog paragraph, and every new file (`system/arc_walk.py`,
`system/arc_walk_evals.py`, all of `interactions/arc_walk/**`,
`docs/adr/0023-arc-walking.md`) added to `framework_files` in the same bump.

## ADR

**New: `docs/adr/0023-arc-walking.md`** — "Arc walking: episodes of a
recomputed plan". Records the episode/plan model (ruling 3), plan-not-persisted
(ruling 4), primary-only filing (ruling 5), and — explicitly — ruling 6: the
passive daily single question is untouched, and this interaction runs only when
a target with N questions is Played. Status `proposed`.

**`docs/adr/0018-candidate-placement.md`** — one amendment row: the additive-
field discipline now has a FOURTH instance, `answered_question_id`, with the
same two-layer split and the same "absent or malformed degrades, never errors"
rule. No decision in 0018 changes.

## Platform twin

Everything the platform reads from the package, by exact name:

| What | Where |
|---|---|
| Normalize a Play target | `arc_walk.normalize_target(value) -> {kind, ref, label, categories}` |
| Closed target kinds | `arc_walk.ARC_TARGET_KINDS` |
| Build the plan (pure) | `arc_walk.build_arc_plan(target, *, questions, categories, coverage, tier, episode_size=None, focus_index=None, objectives=(), cards=(), declined_question_ids=()) -> dict` |
| Plan dict keys | `target`, `focus_label`, `questions[{id,text,category,intent}]`, `episode_size`, `plan_n`, `answered_k` |
| The episode slice + its rendering | `arc_walk.episode_questions(plan) -> list[dict]`, `arc_walk.render_agenda(plan) -> str` |
| Episode size by tier | `arc_walk.episode_size_for(tier, *, override=None) -> int`; knobs `knob.episode_size_basic\|standard\|extreme` in `interactions/arc_walk/interaction.yaml` |
| The stage | `arc_walk.arc_stage_for_session(session, plan, *, user_leaving=False) -> "open" \| "walk" \| "close"` |
| Episode progress (transcript fact) | `arc_walk.answered_plan_question_ids(session, plan) -> tuple[str, ...]` |
| The asked qid (the EXISTING concept) | `arc_walk.asked_question_id(turn)` — reads `turn["question_id"]` on a `role == "lifehug"` turn; the platform's `stamped_question_id` is the same field |
| The question on the table | `arc_walk.question_on_the_table(session, plan) -> str \| None` |
| Structural parse of the turn's field | `conversation_delivery.parse_turn_output(raw)["answered_question_id"]`, enabled by `TurnShape(arc_stage=…)` |
| Closed validation of that field | `arc_walk.validate_answered_question_id(value, *, plan) -> str \| None` |
| The seven lints | `arc_walk.lint_arc_reply(text, *, stage, agenda_announced=False) -> list[dict]` |
| Closed vocabularies | `arc_walk.ARC_TARGET_KINDS`, `arc_walk.VALID_ARC_STAGES`, `arc_walk.ARC_WALK_LINT_CLASSES`, `conversation.ARC_INTENT_KINDS` |
| The prompt leaf to REPLAY verbatim | `interactions/arc_walk/prompt/turn-instructions.md`, via `interaction_registry.compose_interaction_asset("arc_walk", "prompt/turn-instructions.md")`, substituting `{arc_stage}`, `{agenda}`, `{focus_label}`, `{episode_size}`, `{answered_k}`, `{plan_n}` |
| The read-only plan verb | `lifehug.py arc-plan-target (--focus\|--category\|--chapter\|--book\|--queue) [--episode-size N] [--json]` |
| The seat gate | `lifehug.py arc-walk-evals [--live] [--json]` |
| Ranking authority (unchanged) | `question_planner.enriched_pending_questions`, `question_planner.DEFAULT_LANE_POLICY`, `question_planner.qid_key` |

The FILING of an answer to `answered_question_id` is entirely platform-side
(`turn_filing.py`): the package names the question, the host writes the file.

## Acceptance checklist

- [ ] Exactly one new turn-output field exists (`answered_question_id`); no new
      session field, lifecycle status, persisted plan, or state machine.
- [ ] `_output_contract_block` is byte-identical when `arc_stage` is None
      (ruling 6, mechanically).
- [ ] A malformed or absent `answered_question_id` never errors a turn.
- [ ] The plan's order is `enriched_pending_questions` + `build_queue`'s own
      weight expression + `arc_max`; the AST pins hold.
- [ ] The plan is recomputed, never persisted; answered and declined questions
      fall out (ruling 4).
- [ ] `len(plan["questions"]) == plan_n - answered_k`.
- [ ] The opener announces the agenda once and never counts — goldens 1, 3, 5.
- [ ] A tangent, a decline, and a leaving signal each behave — goldens 3, 4, 8.
- [ ] An answer covering two questions names one — golden 6.
- [ ] `arc-walk-evals` passes; the other three eval harnesses are untouched
      and pass.
- [ ] `interactions/conversation/` and `interactions/question_candidate/` are
      byte-identical (their digests do not move).
- [ ] CI green (`test` on 3.11/3.14, `framework-manifest`, `version-bump`);
      handbook parity and embed parity green.
- [ ] `system/version.json` at 193 with every new file in `framework_files`.
- [ ] ADR 0023 added; ADR 0018 gains the fourth-instance row; the interactions
      README's fourth child stops saying PROPOSED.

## Owner closeout

**Look.** The transcript the goldens replay (no provider required):

- *Turn 1 (`open`)*: "Today I'd love to hear about Etherfuse — three things,
  and we'll take them slowly. What made you decide to start it?"
- *Turn 2 (`walk`)*: they answer about the founding → the reply receives it,
  then bridges: "…so the regulation came first and the product second. Who
  did you call the day you decided?" `answered_question_id` names the plan
  question their answer actually landed on.
- *Turn 3 (`walk`, tangent)*: they talk about their father instead. The reply
  follows THEM — no agenda restated, no "back to our list".
- *Turn 4 (`walk`, decline)*: "I'd rather not get into that one." The reply
  moves on without comment.
- *Turn 5 (`close`)*: "We got the founding, the first call, and what it cost —
  that's a good stretch. The rest will keep for whenever you like." No
  question, no count.
- `python3 system/lifehug.py arc-plan-target --focus etherfuse --json` prints
  the plan and writes nothing.

**Judge.**

1. **`plan_n` counts EVERY question in the target, `answered_k` the answered
   ones.** Yes = "k of N" on a Foundation row is a bank fact and the plan's
   open list is exactly the difference.
2. **The plan is recomputed at every Play and never stored.** Yes = resuming
   is "a new episode of a fresh plan", and the only durable memory is the
   declined list that already exists.
3. **Episode sizes basic 4 / standard 6 / extreme 8, as knobs.** Yes = these
   numbers ship as both module constants and manifest knobs, pinned equal.
4. **Primary-only filing.** Yes = an answer covering two questions names one,
   and the compiler's content links do the rest.
5. **The agenda anchor is a "today" cue plus a "hearing" cue, not a fixed
   sentence.** Yes = the model may phrase the announcement its own way and the
   lints still locate the move.

**Done when.** Implementation PR green on CI → v193 tagged on merge →
platform issue #570 P3 pins v193 and consumes the names in the Platform twin
table.

🤖 Generated with Claude Opus via Claude Code
