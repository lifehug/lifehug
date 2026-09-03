---
title: The Interaction Pattern
parent: Handbook
has_children: true
nav_order: 5
---

# The Interaction Pattern

## 1. What it does & what it's for

Ten roles in this system put a model into a seat; seven of them are
children of one of the other three. The founding three: talking with the
user (Chat/Conversation), judging whether a generated question deserves
to exist (Question Judgment), and resolving whether two pending Focus
ideas are actually the same person or theme under different names (Focus
Curation). Before [ADR 0002](https://github.com/lifehug/lifehug/blob/main/docs/adr/0002-interaction-pattern.md),
each of these was an ad hoc prompt string with no shared design, no
research basis, and no gate on which model was trusted to run it — and
the ADR's own Context section names the exact cost of that: a
conversation surface where one mechanism literally returned "No questions
back" with no follow-up logic, follow-up generation unrelated to what
came before it in the same thread, and a story-ingest path that returned
nothing to the user at all. Improving one of the three did nothing for
the others, because nothing forced them to share rules.

An **Interaction** is the fix: a designed, portable, versioned, eval-gated
role definition, packaged as files any qualified model can execute — not
a prompt string embedded in a runtime, and not a description of behavior
that a runtime might drift from. This page defines the pattern itself, so
a reader with zero prior context can add a new interaction, or judge
whether an existing one is being used correctly, without missing a part.
The main use case for a contributor: "I need the AI to do a new kind of
judgment call — do I need a new Interaction, and if so, what are the
required parts?" This page, plus its new-interaction checklist (§6),
answers that.

## 2. The nouns

An **Interaction** is defined once, precisely, in the
[Glossary](../glossary.md): a role definition for the AI in one
situation — purpose, behavior contract, context recipe, scope, and evals,
packaged as files any qualified model can execute. "Interaction" names
the *definition*, not any one model's behavior, and not the code that
runs it. Ten exist today, each with its own handbook page:
[Conversation](conversation.md), [Question Judgment](question-judgment.md),
[Focus Curation](focus-curation.md), and Conversation's seven **children**
— [Question Candidate](question-candidate.md) (placement),
[Focus Candidate](focus-candidate.md) (onboarding),
[Entity Candidate](entity-candidate.md) (identity),
[Arc Walk](arc-walk.md) (arc walking), and
[Timeline](timeline.md) (placing a memory in time), and
[Landmarks](landmarks.md) (the universal dating question set), and
[Reading Room](reading-room.md) (dating from evidence).

**The child-interaction paradigm.** Conversation is the parent; a child
adds exactly ONE goal, a stage-keyed `prompt/turn-instructions.md` leaf
the host substitutes into, ONE optional additive structured-output field
gated on a `TurnShape` flag (absent or malformed degrades to ordinary
Conversation and never errors a turn), and its own lints, goldens, evals
harness, and seat. **Play** on the row that opens one of these means
*approve and start*: the approving write — promote, scaffold, graduate —
runs in the host's background job, so the model claims nothing and waits
for nothing. The fourth child, [Arc Walk](arc-walk.md) (v193), is the one
whose Play approves nothing at all — the questions already exist — so only
the conversation side runs. The paradigm is written once in
`interactions/README.md`;
`train the small interactions first, one model later` is its stated
training path.

The **three-way split** every interaction observes:

- **Definition** — the files under `interactions/<name>/`. OSS,
  versioned, PR-reviewed. This is the **behavior authority**: if a
  runtime's live behavior and the definition ever disagree, the
  definition is right and the runtime has a bug.
- **Runtime** — the loader code that reads the definition and executes a
  turn, one per side: the OSS single-user runtime (e.g.
  `system/conversation.py`, `system/question_judgment.py`,
  `system/focus_curation.py`) and the hosted platform's vendored
  equivalent (multi-user, same definition). Runtimes may differ in
  mechanics — queueing, delivery, storage — but MUST NOT diverge on
  anything the definition specifies: router classification, knob values,
  hard rules.
- **Seat** — which concrete model plays which role, decided by config
  (`role.router`, `role.worker`, `role.planner` in `interaction.yaml`)
  and gated by the eval harness. A model is never assumed competent; it
  is seated only after its outputs pass `evals/` for that interaction.

**Doc-drift impossibility.** Because `prompt/behavior.md` IS both the
prompt sent to the model and the documentation a person reads, there is
structurally only one file, not a prompt plus a separate description of
the prompt that can fall out of sync. This is the same guarantee this
handbook site claims for itself (see the [home page](../)'s "kept honest
by construction" section) — the interaction pattern is where that
guarantee originates in the codebase, and this handbook's own embedded-
`behavior.md` pages (§7 below) are a direct application of the same
idea, one layer up.

**The file roles**, in the fixed load order `interactions/README.md`
specifies (an interaction may omit `router/` or `plan/` if it doesn't
need them):

| File | Role |
|---|---|
| `README.md` | The WHY: research basis, ratified decisions, pointers. Human-first; not injected per-turn. |
| `interaction.yaml` | The manifest: modes, load order, model roles by capability tier, lifecycle knobs, per-block context budgets. Flat scalar YAML only (see below). |
| `prompt/identity.md` | Who the AI is in this role: persona, voice, self-reference rules. Loaded first (stable, cache-friendly). |
| `prompt/behavior.md` | The behavior contract: objectives, numbered hard rules, defaults. The load-bearing file — this is what the model is graded against. |
| `prompt/examples.md` | Canonical good/bad exchanges, each showing the rule it demonstrates or violates. Loaded after behavior. |
| `prompt/turn-instructions.md` | The per-turn task template. Loaded LAST, after per-user and per-session context, so it's the freshest thing the model reads before generating. |
| `router/` *(only if free-form inbound)* | `router.md` (a cheap classifier prompt sorting inbound into intents) + `deflection.md` (the out-of-scope response template). |
| `context/manifest.md` | The deterministic per-turn context recipe: which blocks, in what order, from what sources, under what token budgets. The runtime implements exactly this document. |
| `overlays/<provider>.md` | ONLY verified behavioral deltas for one model provider. Empty is the expected, healthy default. |
| `evals/` | The model contract: `lints.yaml` (deterministic checks), `goldens/` (transcript fixtures with property assertions), `rubrics.md` (binary per-rule judge questions), `personas/` (simulated users). This is what decides which models may be seated. |
| `plan/` *(only if pre-planned turns)* | How a planning loop assembles a plan before the interaction executes it live, turn by turn. |

**Out-of-scope input is politely deflected** — every interaction that
receives free-form inbound (Conversation and its Question Candidate child
do today) carries a `router/deflection.md` template rather than attempting
to improvise a redirect.

Shared vocabulary this page relies on without redefining:
**[Chat, Conversation, Arc card, Session](../glossary.md)** are all
defined once in the [Glossary](../glossary.md).

## 3. How it works: the assembly order and the doc-drift guarantee

Per-turn context is assembled from an interaction's files in a fixed
order — identity first (stable, cacheable), turn instructions last
(freshest, turn-specific) — exactly as each interaction's own
`context/manifest.md` specifies. The reference example, `conversation/context/manifest.md`:
`identity → behavior → examples → profile → record → session →
turn_instructions`. `question_judgment`'s is `identity → behavior →
learned → examples → profile → turn_instructions`; `focus_curation`'s,
the simplest of the three (no learning file, no per-user profile signal
relevant to an identity judgment), is `identity → behavior → examples →
turn_instructions`.

**Registered composition.** `interactions/registry.json` is the closed list of
packages a runtime may execute or seat. `system/interaction_registry.py`
audits each package and resolves explicit inheritance. A child pins an exact
parent version and declares every inherited asset as parent-to-child append or
child leaf authority. Callers cannot select a merge strategy, and provenance
markers show exactly which package supplied each assembled block. Question
Candidate is the first child: it inherits Conversation chat mechanics without
copying them while retaining its own behavior, context, lifecycle, eval, and
seat boundary ([ADR 0018](https://github.com/lifehug/lifehug/blob/main/docs/adr/0018-candidate-placement.md)).

**Why doc-drift is structurally impossible.** A conventional system has
a prompt string somewhere in a runtime, and — if it's disciplined — a
separate wiki page or comment describing what that prompt does. The two
can silently diverge: someone edits the prompt under deadline, the
description doesn't get updated, and the next reader of the description
is reading fiction. The Interaction pattern removes the second
document entirely. `prompt/behavior.md` is read by the runtime verbatim
(as context assembled into a live call) AND read by a human via GitHub
or this handbook's embed (§7). There is one file. A PR that changes
behavior necessarily changes the file everyone — model and human — reads.

**Eval gating.** A model is never assumed competent at a role; `evals/`
is what decides. The four-part shape every interaction's `evals/`
follows: `lints.yaml` (deterministic, no model call — e.g. one question
per turn, banned phrases, a rubric-edit amendment fits its char budget),
`goldens/` (fixture transcripts asserted against real properties),
`rubrics.md` (one binary yes/no question per hard rule — 1:1 with
`prompt/behavior.md`'s numbered rules), and `personas/` (simulated users
whose runs must demonstrate specific properties, e.g. the `grief-fresh`
persona's runs must show deferral). As of this page, `conversation`'s
harness is wired (`lifehug.py conversation-evals`, issue #120);
`question_judgment` and `focus_curation` ship their `evals/` directories
as data only — no engine reads them yet, so **neither interaction has a
seated model today**, exactly as the pattern requires when no harness has
run.

**Tier guidance.** `role.router` / `role.worker` / `role.planner` name
**capability tiers**, never vendor products (ADR 0002's model-agnosticism
rule, restated explicitly in every interaction's owner-decisions
section). The working rule across all five interactions: a
high-volume, low-stakes, per-item call (judging one candidate, routing
one inbound message) is a lower tier (`medium`, or the router's
`haiku-class`); a low-volume, high-stakes call that changes behavior for
every future turn (the weekly rubric edit, the quarterly recalibration)
is a higher tier (`high`, or `sonnet-class`/`role.planner`). Concretely:
`question_judgment` sets `role.worker: medium` / `role.planner: high`;
`focus_curation` — a low-stakes, fully reversible relabeling call with no
rubric-edit mode at all — sets only `role.worker: medium` and omits
`role.planner` entirely, because there is nothing here for a planner tier
to do.

## 4. The algorithm

There is no formula here — the pattern doesn't score anything itself;
each interaction's own judgment (a priority band, a partition, a turn)
is that interaction's algorithm, covered on its own page. What this
section covers instead, since the template's "the real formula with the
real numbers" doesn't transplant to a pattern-level page: the one hard
parsing constraint every interaction's `interaction.yaml` (and any other
runtime-read YAML, such as `evals/lints.yaml`) must honor.

**The YAML constraint.** The repo parses only a flat top-level scalar
subset of YAML (`lifehug_core._parse_simple_yaml`,
`system/lifehug_core.py:557`): `key: value` lines, comments stripped, no
nesting, no lists, no dependency on PyYAML. Every `interaction.yaml`
therefore uses flat dotted keys — `budget.identity: 600`,
`knob.chat_idle_timeout_minutes: 120` — never nested mappings or list
syntax. This is why every interaction's manifest reads as a flat list of
`role.*` / `knob.*` / `budget.*` lines rather than a nested YAML
document; it preserves the designed filename/content roles via
namespacing-by-dots without adding a parsing dependency the
dependency-free runtime doesn't otherwise need.

## 5. In the loop

**What feeds it:** every generation and judgment call already covered on
this handbook's other pages routes through one of the five interactions
here — [Question Candidates](../question-candidates.md)' classifier and
research-expander generation both read the Question-Judgment rubric as
context (§3 of that page); [Focuses & the Autopilot](../focuses.md)'
third dedupe layer *is* the Focus-Curation interaction; the daily/weekly
loop's Chat and Conversation surfaces *are* the Conversation interaction.
**What it feeds:** every one of those consumers gets a single,
versioned, reviewable source of truth for "how does the AI behave here"
instead of a scattered prompt fragment — the exact defect [ADR
0002](https://github.com/lifehug/lifehug/blob/main/docs/adr/0002-interaction-pattern.md)'s
Context section names as the reason this pattern exists. **How it
self-improves:** the eval harness is the mechanism — a new model
candidate is seated only after passing `evals/`, so improving which model
plays a role is a gated upgrade, not a silent swap; and each interaction's
own learning architecture (RUBRIC-EDIT for question-judgment; none, by
design, for focus-curation — see its own page) is covered on that
interaction's page rather than here.

**Classification (Convergence Principle):** the pattern itself does not
have a floor/accelerator classification — it's infrastructure the three
seated interactions build on, not a Loop stage. Each interaction's own
page states its own classification: Question Judgment's JUDGE-context
injection is the floor for candidate quality (every generation reads the
full rubric, unattended); Focus Curation is explicitly the smallest,
least-autonomous of the three by design — it is purely an accelerator for
one narrow judgment call, since the deterministic door-guard and
roster-fold dedupe layers beneath it are already the floor (see [Focuses
& the Autopilot](../focuses.md) §2).

## 6. Where it lives

| Concern | Location |
|---|---|
| The pattern's own definition | `interactions/README.md` |
| Closed package registry | `interactions/registry.json` |
| Nine shipped interactions | `interactions/conversation/`, `interactions/question_judgment/`, `interactions/focus_curation/`, `interactions/question_candidate/`, `interactions/focus_candidate/`, `interactions/entity_candidate/`, `interactions/arc_walk/`, `interactions/timeline/`, `interactions/landmarks/` |
| Registry, composition, and package audit | `system/interaction_registry.py` |
| The flat-YAML parser every `interaction.yaml` depends on | `system/lifehug_core.py:557`, `_parse_simple_yaml` |
| Eval CLIs | `lifehug.py conversation-evals`, `lifehug.py question-candidate-evals`, `lifehug.py focus-candidate-evals --json`, `lifehug.py entity-candidate-evals --json`, `lifehug.py arc-walk-evals --json`, `lifehug.py timeline-evals --json`, `lifehug.py landmarks-evals --json` |
| New-interaction checklist | `interactions/README.md`'s "The new-interaction checklist" section (12 steps: README → `interaction.yaml` → `prompt/` → `router/` if needed → `context/manifest.md` → `overlays/` → `evals/` → `plan/` if needed → vault-contract registration → `framework_files` registration → an ADR → no default seat until evals pass) |
| Guard tests | `tests/test_interaction_evals.py`, `tests/test_conversation_router.py`, `tests/test_question_judgment.py`, `tests/test_focus_duplicate_curation.py` (repo-verify exact names before citing in a PR) |

**Change-safely notes.** A new interaction that skips the
definition/runtime/seat split, or ships without an eval harness, is a
design defect per ADR 0002's Consequences — not a valid shortcut for a
"simple" case. Behavior changes to any of the eight interactions go
through their own `interactions/<name>/` files and evals, never through
ad hoc edits to a runtime's prompt strings; a runtime-side divergence
from the definition is a runtime bug, not a legitimate platform variant.
Model-specific tricks belong ONLY in `overlays/<provider>.md`, and only
once a real, verified delta is found — never speculatively in the core
`prompt/*.md` files.

## 7. Decisions

- [ADR 0002 — The Interaction pattern for AI-driven surfaces](https://github.com/lifehug/lifehug/blob/main/docs/adr/0002-interaction-pattern.md) — this page's whole subject: the three-way split, the file roles, the model-agnosticism rule, and the arc-card contract amendment.
- [ADR 0007 — The Question-Judgment Interaction](https://github.com/lifehug/lifehug/blob/main/docs/adr/0007-question-judgment-interaction.md) — the second interaction built to this pattern; see [Question Judgment](question-judgment.md).
- `interactions/README.md` — the pattern's own canonical document; this page summarizes it for the handbook but the source file is the authority on any wording dispute.
- Each seated/unseated interaction's own README (`interactions/conversation/README.md`, `interactions/question_judgment/README.md`, `interactions/focus_curation/README.md`) — the "why" for that specific interaction, one level more specific than this page.
