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
   An interaction may also carry step-specific prompt files; their specialized
   builder loads them only for that step. They never join the ordinary load
   order implicitly (Conversation's candidate-placement files are the first
   example).
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
