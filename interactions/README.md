# The Interaction pattern

This directory holds Lifehug's **Interactions**: designed role definitions
for the AI, one per situation the system puts a model into. This file
defines the pattern itself, so that a model with no prior context can add a
new interaction without missing a part. If you are about to build or modify
an interaction, read this file first, then the interaction's own
`README.md` (its "why").

## What an Interaction is

> An Interaction is a role definition for the AI in one situation:
> purpose, behavior contract, context recipe, scope, and evals, packaged as
> files any qualified model can execute. The definition lives in the
> framework (`interactions/<name>/`); each runtime loads it; a model is
> "seated" in it only after passing its eval harness. Out-of-scope input is
> politely deflected.

This is the ratified nomenclature (owner-approved design, 2026-08-11). Use
it precisely: "interaction" names the *definition*, not any one model's
behavior, and not the code that runs it.

## Whispers

A **whisper** is information woven into a conversation that fits naturally,
drawn from an arc that has developed, and serving a **second agenda beyond the
conversation's primary one** (owner-set, 2026-08-23). It is not a second
interaction and not a new stage: it rides the week's arc card into an ordinary
Conversation turn, and the interaction's own judgment decides whether it fits
here at all.

Three rules bind every whisper, whatever its agenda:

1. **Only where it fits.** After the thought the person is in has closed, in
   their own words — never as a change of subject.
2. **At most one per conversation.** Structurally (a session that has raised
   one carries no whisper on the next turn) and as a scored lint.
3. **Never penalized.** A whisper that lands is a gift, not a cost the loop
   trades off — the weekly arc-yield pass is told so explicitly.

The first kind is the **timeline whisper** (v196): the same move applied to
placing moments in time. The card carries a timeline keystone's real probe,
its identity (`tl:<anchor-slug>`) and the person's own landmarks; any
precision is accepted, a calendar year is never demanded, and the answer files
through `timeline-place`. Later kinds name their own agenda and inherit the
three rules above.

## The three-way split

Every interaction separates three things that are easy to accidentally
merge into one artifact:

- **Definition** — the files under `interactions/<name>/`. OSS, versioned,
  PR-reviewed. This is the **behavior authority**: if a runtime's live
  behavior and the definition ever disagree, the definition is right and
  the runtime has a bug.
- **Runtime** — the loader code that reads the definition and executes a
  turn, one per side: the OSS single-user runtime (`system/conversation.py`,
  landing in PR 2 / issue #115) and the hosted platform's vendored
  equivalent (multi-user, same definition). Runtimes may differ in
  mechanics (queueing, delivery, storage) but MUST NOT diverge on anything
  the definition specifies — router classification, knob values, hard
  rules.
- **Seat** — which concrete model plays which role, decided by config
  (`role.router`, `role.worker`, `role.planner` in `interaction.yaml`) and
  gated by the eval harness. A model is never assumed competent; it is
  **seated** only after its outputs pass `evals/` for that interaction.

Because the definition's `prompt/behavior.md` file IS both the prompt sent
to the model and the documentation a person reads, **doc-drift is
structurally impossible**: there is only one file, not a prompt plus a
description of the prompt that can fall out of sync.

## File roles and load order

Every interaction's tree carries these parts (an interaction may omit
`router/` or `plan/` if it doesn't need them — see the checklist below).
Per-turn context is assembled from these files in a fixed order — identity
first (stable, cacheable), turn instructions last (freshest, turn-specific)
— exactly as each interaction's own `context/manifest.md` specifies:

1. **`README.md`** — the WHY: research basis, ratified decisions, pointers.
   Human-first; a model benefits from it too but it is not injected
   per-turn.
2. **`interaction.yaml`** — the manifest: modes, load order, model roles by
   capability tier, lifecycle knobs, per-block context budgets. Flat scalar
   YAML only (see the repo-wide YAML constraint below).
3. **`prompt/identity.md`** — who the AI is in this role: persona, voice,
   self-reference rules. Loaded first in the per-turn assembly (stable,
   cache-friendly).
4. **`prompt/behavior.md`** — the behavior contract: objectives, numbered
   hard rules, defaults. The load-bearing file — this is what the model is
   graded against.
5. **`prompt/examples.md`** — canonical good/bad exchanges, each showing
   the rule it demonstrates or violates. Loaded after behavior so the model
   sees the rule and then the shape of following it.
6. **`prompt/turn-instructions.md`** — the per-turn task template. Loaded
   LAST, after the per-user and per-session context blocks, so it is the
   freshest thing the model reads before generating.
7. **`router/`** (only if the interaction receives free-form inbound
   messages, not just replies to a delivered prompt) — `router.md`, the
   cheap classifier prompt that sorts inbound into intents, and
   `deflection.md`, the out-of-scope response template.
8. **`context/manifest.md`** — the deterministic per-turn context recipe:
   which blocks get assembled, in what order, from what sources, under
   what token budgets. The runtime implements exactly this document.
9. **`overlays/<provider>.md`** — one file per supported model provider,
   holding ONLY verified behavioral deltas for that provider. An empty
   overlay means the core files are fully portable to that provider — this
   is the expected state until a real delta is found and verified.
10. **`evals/`** — the model contract: `lints.yaml` (deterministic
    checks), `goldens/` (transcript fixtures with property assertions),
    `rubrics.md` (binary per-rule judge questions), `personas/` (simulated
    users the goldens run against). This is what decides which models may
    be seated.
11. **`plan/`** (only if the interaction has pre-planned turns, e.g. an
    arc) — how the planning loop assembles a plan before the interaction
    executes it live, turn by turn.

The exact per-turn assembly order is documented per-interaction (see
`conversation/context/manifest.md` for the reference example: `identity →
behavior → examples → profile → record → session → turn_instructions`).

## The new-interaction checklist

To add a new interaction `interactions/<name>/`:

1. Create `README.md` — research basis (why this shape) + the decisions
   that bind it, in the voice of Deliverable 2a of
   `docs/pr-specs/114-interactions-scaffold.md` (mission tie-in, what the
   interaction is, research pointers, owner decisions, how it's built, how
   to eval).
2. Create `interaction.yaml` — modes, load order, model roles by tier,
   lifecycle knobs, context budgets. Flat scalar YAML only (see below).
3. Create `prompt/` — at minimum `identity.md`, `behavior.md`,
   `examples.md`, `turn-instructions.md`.
4. Create `router/` ONLY if the interaction receives free-form inbound
   (i.e. is not purely "reply to a delivered prompt") — `router.md` +
   `deflection.md`.
5. Create `context/manifest.md` — the deterministic assembly order and
   token budgets, matching `interaction.yaml`'s `budget.*` keys.
6. Create `overlays/` — one file per supported provider; start every one
   empty with the convention header (see Model-agnosticism rule below).
7. Create `evals/` — `lints.yaml`, `goldens/` (fixtures + a README
   describing the format if goldens aren't filled yet), `rubrics.md`,
   `personas/`.
8. Create `plan/` ONLY if turns are pre-planned (an arc, a template, a
   script) rather than generated fresh each turn.
9. Register any new durable state the interaction needs in
   `system/vault_contract.json` (data paths) and, if the interaction's own
   files must ship to existing vaults, add the framework path there too.
10. Add EVERY new file under `interactions/<name>/` to `framework_files` in
    `system/version.json` — the interaction definition is framework-owned
    and must reach vaults on upgrade, exactly like any other shipped file.
11. Write or extend an ADR under `docs/adr/` recording the decision to add
    this interaction and any durable-data contract it introduces.
12. Models are seated in the interaction only after passing its
    `evals/` harness — a new interaction ships with no default seat until
    the harness says who may hold it.

## Registration and composition

`interactions/registry.json` is the closed list of executable Interaction
packages. A complete-looking directory that is absent from the registry is not
an Interaction that a runtime may execute or seat. `system/interaction_registry.py`
validates the registry and package manifests and provides the package audit.

An Interaction may declare `extends: <registered-id>` plus an exact
`extends.version`. A child declares every composed text asset under flat-scalar
`composition.append` (parent-to-child, with provenance) or `composition.leaf`
(child authority only). The two sets are disjoint and callers cannot choose a
different policy. This is behavioral inheritance without copy drift: a child
reads current parent files directly, and a parent-version mismatch forces
review. Question Candidate is the first composed Interaction; it inherits
Conversation chat mechanics while keeping its own identity, lifecycle,
context, evals, registration, version, and seat surface (ADR 0018).

## The child-interaction paradigm

**Conversation is the parent.** Every other conversational surface in the
product is a CHILD of it that adds exactly ONE goal. Seven are built
(v188, v189, v190, v193, v195, v197, v204); the shape below is what they
repeat. Deviating from it is a design defect, not a variant.

1. **One goal, named.** Placement, onboarding, identity, arc walking,
   placing a memory in time, the dating question set, dating from evidence.
   A child that would carry two goals is two children.
2. **Composition, never a fork.** `extends: conversation` plus an exact
   `extends.version`; `prompt/identity.md`, `prompt/behavior.md`,
   `prompt/examples.md` and `router/*` append parent-to-child, while
   `prompt/turn-instructions.md` and `context/manifest.md` are leaf
   (child authority). Ordinary Conversation stays byte-identical
   ([ADR 0018](../docs/adr/0018-candidate-placement.md)).
3. **A stage-keyed prompt leaf the host substitutes into.** The child's
   `prompt/turn-instructions.md` is REPLAYed verbatim by the caller with
   `{<goal>_stage}` and the target's own placeholders filled in. The
   stage is derived from the transcript, never stored.
4. **Exactly ONE additive structured-output field — or none at all.**
   Optional; absent or
   malformed degrades to ordinary Conversation behavior and never errors
   a turn; gated on a `TurnShape` flag so the output-contract appendix is
   byte-identical when the gate is `None` (a required test on every
   child). Two validation layers: structural in
   `system/conversation_delivery.py` (owns no vocabulary, returns `None`,
   never raises) and closed in the child's own module (owns the roster —
   though not always the roster's contents: `entity_setup.maps_to` is
   checked against slugs the CALLER supplies). The rule's INTENT is *no new
   vocabulary per child*, and v204 is the one case that reads it in the
   strict direction: `reading_room` mints NO field and REUSES two that
   already exist — `placed` and `landmark` — behind its single `TurnShape`
   gate. Reuse is always better than a third shape for the same fact; a
   child inventing a field a sibling already owns is the defect this rule
   exists to prevent.
5. **Its own lints, goldens, and evals harness.** `<child>-evals` is the
   seat gate; passing Conversation alone never seats a model in a child.
6. **Its own version bump, ADR amendment row, and `framework_files`
   entries**, in the same PR.

### Play semantics: approve + start

**Play is one verb: it APPROVES the thing and STARTS its conversation.**
The approving write runs in the host's background job — promote the
question candidate, scaffold the focus, graduate the entity — and the
conversation opens immediately, never waiting on it. So the model writes
nothing, approves nothing, and claims nothing: by the time it speaks the
act is already done. Its job is to state that fact ONCE, as an aside on
the first reply, and to accept a correction as a MOVE rather than a
resolution. "Play is read-only" / "Play never promotes" is **retired
vocabulary** — platform ADR 0020 (`lifehug-platform/docs/adr/0020-play-
is-a-deep-link.md`) amended ADRs 0018, 0021, and 0022 in place.

A **Play target** (proposed, platform issue #570) generalizes the verb:
`{kind, ref, goal, question_ids[], context}` — candidate, focus, entity,
question, chapter, book, or queue — so one endpoint and one tab renderer
serve every Play, and the daily loop becomes a *scheduled* Play. The
package's own half of that shape is real as of v193:
`arc_walk.normalize_target` and `arc_walk.ARC_TARGET_KINDS` cover the five
kinds that carry a SET of questions (a single-question Play is an ordinary
chat and needs no plan).

Play on a Foundation row does NOT approve anything — the questions already
exist — so the "approve + start" half is a no-op there and only the
conversation side runs.

### The seven children

| Child | The one goal | Additive output field | Stages | Stage source | Closed validator | Lints |
|---|---|---|---|---|---|---|
| `question_candidate` (v188) | **placement** — where the answered question belongs | `placement: {category} \| null` | `assert` · `ask` · `settled` | `question_candidate.placement_stage_for_session` | `question_candidate.validate_placement` (category roster) | seven `placement_gates.*` |
| `focus_candidate` (v189) | **onboarding** — what the focus is about and how far it reaches | `focus_setup: {objective?, type?, relationship?, living?, label?} \| null` | `establish` · `settled` | `focus_candidate.focus_stage_for_session` | `focus_candidate.validate_focus_setup` (`roadmap.FOCUS_TYPES`, `focus_candidate.FOCUS_RELATIONSHIPS`) | six `focus_setup_gates.*` |
| `entity_candidate` (v190) | **identity** — names, relation, living, and whether the roster already holds them | `entity_setup: {aliases?, relationship?, living?, type?, maps_to?, start_focus?} \| null` | `establish` · `settled` | `entity_candidate.entity_stage_for_session` | `entity_candidate.validate_entity_setup` (`entity_roster.ENTITY_TYPES`, `focus_candidate.FOCUS_RELATIONSHIPS`, caller-supplied roster slugs) | seven `entity_setup_gates.*` |
| `arc_walk` (v193) | **arc walking** — work a target's open questions casually, in resumable episodes | `answered_question_id: "<qid>" \| null` | `open` · `walk` · `close` | `arc_walk.arc_stage_for_session` | `arc_walk.validate_answered_question_id` (exact membership in the episode's recomputed plan) | seven `arc_walk_gates.*` |
| `timeline` (v195, amended v196) | **placing a memory in time** — without ever demanding a year | `placed: DateRecord-shaped \| null` (a range with a basis is first-class; there is no deferral shape) | `open` · `place` · `close` | `timeline_interaction.timeline_stage_for_session` | `timeline_interaction.validate_placed` (`chronology.GRANULARITIES\|CONFIDENCES\|BASES`, EDTF parseability, exact membership in the caller-supplied anchors) | six `timeline_gates.*` |
| `landmarks` (v197) | **the always-present dating question set** — the handful of dated facts every other memory hangs on | `landmark: {domain, label, rung values, date?, span?, skipped?} \| null` (a vague answer is an answer) | `open` · `ask` · `close` | `landmarks_interaction.landmark_stage_for_session` | `landmarks_interaction.validate_landmark` (closed domain set from `questions.yaml`, ladder rungs only, every date normalized through `chronology.parse_edtf`) | five `landmark_gates.*` |

| `reading_room` (v204) | **dating from evidence** — turn what is physically in the room into dated facts | NONE of its own: it REUSES `placed` (the timeline lane's) and `landmark` (the landmarks lane's), both opened by one gate | `open` · `work` · `close` | `reading_room.reading_room_stage_for_session` | `reading_room.validate_evidence` (delegates the vocabularies to `timeline_interaction.validate_placed`, then applies each evidence basis's own honesty ceiling) + `landmarks_interaction.validate_landmark` | five `reading_room_gates.*`, two of them SHARED (`never_proposes_a_date` = `timeline_interaction.proposes_a_date`, `no_pressure` = `landmarks_interaction.pressure`) |

The `TurnShape` gates, in order: `placement_stage` · `focus_stage` ·
`entity_stage` · `arc_stage` · `timeline_stage` · `landmark_stage` ·
`reading_room_stage`. Every one defaults to `None`.

`reading_room` is the one child that RECOMPUTES its own plan mid-session —
evidence → record → recompute → next ask — which is why it is a session
rather than a question. The plan is a pure function of the graph
(`timeline.dig_plan`, the same greedy `keystones` runs, extended to `k`) and
is never persisted, exactly as `arc_walk`'s is not.

`arc_walk` is the one child whose "roster" is computed rather than read:
its plan is rebuilt from the bank at every Play and never persisted
([ADR 0023](../docs/adr/0023-arc-walking.md)), so the closed layer's
membership list is an object, not a file. Its stage also takes ONE caller
fact beyond the transcript — `user_leaving`, the router's "I need to go"
signal — which forces `close` from any point in the episode.

### Train the small interactions first, one model later

Each goal is trained as its own child with its own goldens and harness,
because a small, gated behavior is testable and a large vague one is not.
The target a child works on is **data the model reads in the prompt**
(goal, anchor, agenda) — not a different program — so a later single
model can learn all four as one skill without any child being rewritten.
v193 is the proof of that claim: `arc_walk`'s agenda is literally text
substituted into a leaf, and the only code it needed was an ordering, a
stage, and one validator.

### Proposed, not built

Future children the paradigm anticipates, with no files under
`interactions/` yet: none today. The last entry here — `reading_room`,
seeded by `system/research/go-deep.md` — shipped in v204.

## Model-agnosticism rule

The behavior contract lives in portable prompt and context files —
`prompt/identity.md`, `prompt/behavior.md`, `prompt/examples.md`,
`router/`, `context/manifest.md`. **No model-specific tricks belong in
these core files.** If a provider genuinely needs different handling
(tokenizer quirk, formatting preference, a verified failure mode), the
delta goes in `overlays/<provider>.md` ONLY, and only once it has been
verified — not speculatively. An interaction with all-empty overlays is
the default, healthy state: it means the core files are fully portable.

## The YAML constraint

The repo parses only a flat top-level scalar subset of YAML
(`lifehug_core._parse_simple_yaml`, `system/lifehug_core.py:557`): `key:
value` lines, comments stripped, no nesting, no lists, no dependency on
PyYAML. Every `interaction.yaml` (and any other YAML file a runtime reads,
such as `evals/lints.yaml`) therefore uses **flat dotted keys** — e.g.
`budget.identity: 600`, `knob.chat_idle_timeout_minutes: 120` — never
nested mappings or list syntax. This preserves the designed filename and
content roles (namespacing by dots) without adding a parsing dependency.
