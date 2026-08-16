# Context manifest — the per-turn assembly recipe

This document specifies the deterministic per-turn context assembly.
**PR 2 implements exactly this** — this file is the spec, not a
description of code that already exists. Both runtimes (OSS
`system/conversation.py` and the hosted platform's vendored loader)
assemble context in this same order from the same rules; they may not
diverge.

## Assembly order

`[stable, cached]`

1. **`identity`** — `prompt/identity.md`, verbatim.
2. **`behavior`** — `prompt/behavior.md`, verbatim.
3. **`examples`** — `prompt/examples.md`, verbatim (or a relevant subset
   if truncation is needed to fit `budget.examples`).

`[per-user]`

4. **`profile`** block — this user's name, active focuses, escalation
   states (which topics are cleared for deeper follow-up per behavior.md
   rule 7), and rumination cooldowns (which topic categories are currently
   backed off per behavior.md rule 13).

`[per-session, but drawing on the whole vault]`

5. **`record`** blocks — topic-relevant answers and wiki excerpts, a
   timeline span for the topic in play, entities in play, and candidate
   sibling threads. Every excerpt carries its provenance ID in the form
   `[A14b, 2026-03-14] "…"` so that insight claims can cite receipts
   (behavior.md rule 6 requires this — an insight claim with no
   provenance ID behind it is not backed by anything real).

6. **`asking_supply`** block (issue #168, ADR 0016) — the session focus's
   own held bank questions: a header line naming the focus and its
   answered/total count, followed by up to `knob.asking_supply_top_k`
   unanswered questions from that focus's categories, each rendered
   `[{qid}] {text}`. Sits here — after `record`, before `session` — because
   it is per-session-but-whole-vault-derived exactly like `record` (it
   reads the bank and the roadmap, not just this session's own turns) and
   changes only as slowly as the bank itself, cache-tier correct alongside
   `record`. Producer: `conversation._assemble_asking_supply_block`.
   Resolves the focus via the ladder documented in `system/conversation.py`
   (arc/turn question ids → the planner's category → focus index); a
   session with no resolvable focus (a story session, most often) renders
   this block as an honest empty string, never a fabricated focus. Reuses
   `question_planner.enriched_pending_questions`'s own ranking gates
   (rumination cooldown, escalation) rather than re-deriving weights, and
   excludes any qid this session has already recorded as declined
   (`session["declined_question_ids"]`, additive and session-scoped — see
   `prompt/behavior.md` rules 3/6/9 and the Defaults for how this block is
   actually used in a turn).

`[per-session, this session only]`

7. **`session`** block — the active arc card (see
   `plan/arc-templates.md`), a rolling summary of the session so far, and
   the recent turns verbatim (not summarized — the model needs the exact
   words just exchanged).

`[last]`

8. **`turn_instructions`** — `prompt/turn-instructions.md` with its
   `{placeholder}` slots filled for this specific turn.

## Rules

- **Token budgets** come from `interaction.yaml`'s `budget.*` keys, one
  per block above (`budget.identity`, `budget.behavior`, `budget.examples`,
  `budget.profile`, `budget.record`, `budget.asking_supply`,
  `budget.session`, `budget.turn_instructions`). A runtime that assembles a
  block over its budget must trim that block, not silently ignore the
  budget. `budget.asking_supply`'s 400 tokens caps the BLOCK SIZE only
  (Top-K small, "whisper, not flood") — it says nothing about how many of
  those questions may be asked across a session; that is quality-governed,
  not counter-governed (`prompt/behavior.md`'s Defaults).
- **Top-K small.** The `record` block is always a small, relevance-ranked
  top-K selection. The whole corpus (all of a user's answers and wiki
  pages) is never loaded into a single turn's context — this is a hard
  constraint, not a performance nicety, and it is what keeps the
  interaction portable to smaller-context models via `role.router` /
  `role.worker` tiering.
- **Provenance is mandatory** on every `record` excerpt. Behavior.md rule
  6 (insight claims must cite receipts) cannot be honored by a model that
  wasn't given the receipts in the first place — provenance IDs are how
  the context recipe makes that possible.
- **Order is cache-optimal.** Stable blocks (`identity`, `behavior`,
  `examples`) come first because they don't change turn to turn within a
  session and are shared across users — this lets provider-side prompt
  caching do its job. Per-user and per-session blocks come next because
  they change slowly. `turn_instructions` comes last because it changes
  every single turn — putting the most volatile content last maximizes
  the stable cached prefix.
- **Identical in both runtimes.** The OSS single-user runtime and the
  hosted platform's multi-user runtime implement this exact same
  assembly order and these exact same rules. Differences in how a runtime
  fetches or stores the underlying data (SQLite vs a hosted DB, a local
  file vs a service call) are fine; differences in the assembly order,
  the budget semantics, or the provenance requirement are not.

## Closing prompt assembly (ADR 0015)

The closing prompt (`build_closing_prompt`) is a separate builder from the
per-turn assembly above — it does not go through `assemble_context` — but
it is bound by the same content-first requirement: it must actually read
the conversation, not just `mode` + `rolling_summary`.

- **The FINAL USER TURN is verbatim and unbudgeted.** The last turn with
  `role: user` is included in full, regardless of length — it is never
  truncated or dropped by `budget.closing_transcript` or any other budget.
  It is the reason a reply is owed, and the close responds to it first.
- **Earlier turns respect `budget.closing_transcript`** (a flat
  `interaction.yaml` token budget, same units and truncation convention as
  every `budget.*` key above). When the window is tight, the OLDEST
  preceding turns yield first — the most recent context survives.
- **`rolling_summary`, when non-empty, is included** as older context the
  recent-turns window dropped — additive, not a substitute for the
  transcript above it (the pre-ADR-0015 builder read only this field,
  which the hosted platform never wrote and which never contained the
  message actually being replied to; that gap was the two incidents' root
  cause).
- **Starvation is refused, not rendered.** When there are no user turns
  AND no non-empty `rolling_summary`, `build_closing_prompt` raises
  (`conversation.ConversationPromptError`) instead of emitting a prompt
  that asks a model to appreciate nothing. The engine
  (`conversation_delivery._deliver_closing`) degrades per its own table —
  see ADR 0015 — rather than ever shipping a starved prompt to a model.
