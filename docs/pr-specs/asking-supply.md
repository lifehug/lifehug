# Contract: asking-supply

## Why

Owner-designed (2026-08-16). Conversations improvise follow-ups but are
blind to the asking supply: a session about a focus never sees that
focus's unanswered bank questions, so the interviewer can't advance the
author's real goal ("writing enough about them"). Owner rulings, all
binding:
- The conversation interaction's tight scope is DELIBERATELY WIDENED by
  exactly one capability: offering and asking held bank questions from
  the session's focus. Outside the (widened) scope the model still
  bounds or defers — the deflection posture is unchanged. ADR 0016
  records this as a scope amendment.
- Weave where natural; respond-first stays supreme; a held question is
  offered as the declinable door, introduced honestly as held, never
  passed off as improvised.
- NO per-session cap: as many held questions as belong in a GREAT
  conversation — quality-governed (the mission test + naturalness
  evals), not counter-governed. The protections that remain are about
  respect: declined questions never return (rule 4); cooled topics stay
  cooled (rule 13); escalation gates hold (rule 7).
- The user-invitation hatch is SEMANTIC, judged by the worker model in
  its structured output, FAILING TOWARD ASKING when unsure ("that's all
  I remember", "what else you got", "any other questions", a trailing
  openness all count). Detection is not a phrase list.
- Coverage numbers (answered/total) ride in context but are NEVER
  volunteered — spoken only when the user asks about progress.

## Binding facts (as of origin/main v178 — verify, they are from a
fresh recon with file:line refs)

- Context assembly: `interactions/conversation/context/manifest.md`
  (7 blocks, cache-tiered order, budget-or-trim, Top-K-small,
  provenance, cross-runtime-identical);
  `conversation.py::ASSEMBLE_CONTEXT_BLOCK_ORDER` (~:108) pinned to
  interaction.yaml's `load_order` by
  tests/test_v150_conversation_store.py:296. `assemble_context`'s
  caller-override `blocks` dict accepts ONLY `profile`/`record` today.
  interaction.yaml is flat-scalar-only.
- Behavior rules 1–13 are FROZEN in number (1:1 with lints.yaml ids and
  rubrics; RUBRIC_CLAUSE_COUNT=13 in interaction_evals.py:150) — the
  weave clauses AMEND rules 3 (grammar carve-out), 6 (the door slot),
  7 (gates hold); the scope widening is stated at rule 9 (scope) and in
  Defaults; NO new rule number.
- The engine gate: `conversation_delivery.decide_turn_shape` (~:489)
  computes `question_allowed = planned_question is not None and
  user_turns < target`; a question past target trips the BLOCKING lint
  `question_not_permitted` (~:457) and the turn is discarded to the
  fallback pair. The turn's structured output contract
  (`_output_contract_block`, ~:286) already carries
  `followup_question`/`question_free`.
- "Open Questions" ALREADY MEANS wiki-synthesized questions in this
  codebase (question_candidates.harvest_wiki_questions) — hence the
  block name `asking_supply`.
- Focus derivation ladder (sessions have NO focus field):
  arc.question_id / turn question_ids → `_chain_root` → `qid[0]` →
  `question_planner.build_focus_index()["cat_to_focus"]` → roadmap
  focus. Story sessions may resolve nothing → block honestly empty.
- The open-question pull primitive is one line over existing parsers:
  `[q for q in parse_questions(bank) if q["category"] in
  set(focus["categories"]) and not q["answered"]]`; ranking discipline
  (rumination ×0.25, escalation gate) lives in
  `question_planner.enriched_pending_questions` — REUSE its gates,
  never re-derive (recurring-defect doctrine).
- Prior-art caps ("whisper, not flood") apply to the BLOCK SIZE (Top-K
  small), not to conversational usage (owner removed the usage cap).
- Consumption semantics precedent: `questions/next` = a pick, not a
  delivery (nothing marked sent; answering marks answered). Turns
  already carry `question_id`; `_filed_question_ids` chains replies.
- The platform inherits via pin: the pinned `assemble_context` must
  accept `asking_supply` in the `blocks` override (the platform resolves
  content from projections and passes it in). Keep the OSS producer
  vault-local; keep the override additive.
- 21 pre-existing env failures on clean origin/main in this workspace;
  zero delta; CI arbiter; version = next free (expect 179); changelog
  STRING; handbook embed lockstep for behavior.md
  (EmbedParityTests).

## Scope

1. **The `asking_supply` block.** New context block between `record`
   and `session` (cache-tier correct): header line
   `Focus: {label} — {answered} of {total} answered` + up to
   `knob.asking_supply_top_k` (default 3) unanswered questions as
   `[{qid}] {text}`, selected through the planner's existing gates
   (rumination cooldown, escalation; declined-in-session ids excluded —
   see 4). `budget.asking_supply: 400`. Producer:
   `_assemble_asking_supply_block(session, vault_root)` resolving the
   focus by the ladder; empty string when no focus or no supply (never
   fabricated). `assemble_context` accepts `asking_supply` in the
   `blocks` override (platform seam). manifest.md + interaction.yaml
   `load_order` + ASSEMBLE_CONTEXT_BLOCK_ORDER updated together (the
   parity test forces it).
2. **Behavior amendments (within frozen numbering).**
   - Rule 3 carve-out: a held question from ASKING_SUPPLY may be asked
     verbatim-or-lightly-adapted as the turn's one question, introduced
     as held ("Something I've been holding about {label}: …") — the
     cued-invitation default stands for everything else.
   - Rule 6: the held question is a valid declinable door.
   - Rule 9 + Defaults: the scope statement (this widening; outside it,
     bound or defer — deflection unchanged); the no-cap
     quality-governed doctrine in the owner's framing ("as many as
     belong in a great conversation"); coverage numbers never
     volunteered, answered when asked; when unsure whether the user
     invited another question, ASK (fail toward asking).
   - turn-instructions: the ASKING_SUPPLY block's usage note + the new
     output field (below).
3. **The invitation hatch (semantic, engine-honored).**
   - The turn's structured output gains `user_invited_question: bool`
     (additive) — the worker's judgment that the user's latest message
     invites another question (explicit requests AND open-ended
     receptivity; unsure → true when the message signals the current
     thread is spent).
   - `decide_turn_shape`/the gate: past target, a question is permitted
     IFF the model output declares `user_invited_question` AND the
     asked question is drawn from ASKING_SUPPLY (its qid appears in the
     block) — the blocking lint amends from "no questions past target"
     to "no UNINVITED questions past target"; an uninvited question is
     still discarded exactly as today. Within target, behavior
     unchanged (planned questions + the new held-question option).
   - Asked-question bookkeeping: the lifehug turn stamps the held
     question's `question_id` (a pick, not a delivery — no rotation/
     queue/ledger mutation); the reply files against it through the
     existing turn-chain, marking the bank naturally.
4. **Session-scoped decline memory.** A held question offered and
   declined (user moves past it / says no) is recorded on the session
   (additive field `declined_question_ids: [qid]`, written by the
   engine when the next user turn does not engage the offered qid — a
   simple deterministic rule: offered qid + next user turn filed
   against a different/no qid ⇒ declined) and excluded from the block
   for that session AND its same-focus continuations. Rule 4's
   "never re-offer" made structural. (Cross-session global decline
   state is OUT — future decisions-loop work.)
5. **Evals.** Goldens: (a) natural weave — supply present, moment
   invites, held question as the door, introduced as held; (b)
   uninvited-past-target — supply present, user still mid-story, no
   question, `user_invited_question: false`; (c) hatch — "what else you
   got?" past target ⇒ question asked from supply,
   `user_invited_question: true`; (d) empty-supply honesty — hatch with
   no supply ⇒ honest no-questions reply naming answered/total, no
   fabricated question; (e) coverage-not-volunteered rubric clause.
   New golden property ids flagged for platform vocabulary
   reconciliation. Rubrics: the great-conversation clause (many held
   questions fine when they belong).
6. **ADR 0016**: the scope amendment, the no-cap ruling, fail-toward-
   asking, the pick-not-delivery semantics, decline memory, the block's
   name rationale, platform riders (projection-resolved block via the
   blocks override; worker projection wiring prerequisite; envelope
   join with the filed-answers overlay).
7. Version bump + changelog; handbook conversation-page embed lockstep;
   manifest/interaction.yaml/turn-instructions updated together.

Out: router changes (taxonomy frozen; not needed) · platform block
resolution (rides the pin bump after the worker wiring lands) ·
cross-session decline state · arc-card generation (#412) · any change
to close behavior (v178).

## Test plan

`tests/test_asking_supply.py`: block assembly (focus ladder incl.
chat-qid and story-no-focus cases; top-k; gates respected; declined
excluded; empty honest); gate honors invitation past target and still
discards uninvited; stamps question_id on held asks; decline detection
rule; blocks-override acceptance; manifest/order parity. Goldens per
Scope 5 through `conversation-evals` keyless layers. Update
turn-shape/output-contract tests. Zero delta vs 21-failure baseline.

## Definition of done

TEMPLATE.md: version bump, ADR 0016, behavior+handbook lockstep,
new-property flags for the platform, evidence comment with a real
keyless turn build showing the ASKING_SUPPLY block rendered for a
synthetic focus session AND the hatch honored past target.

🤖 Contract authored by Claude Fable 5 via Claude Code
