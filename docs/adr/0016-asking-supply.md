# ADR 0016: Asking-supply — conversations see and ask the focus's held questions

Date: 2026-08-16
Status: proposed

## Context

Issue #168. Conversations improvise follow-ups turn to turn but are blind
to the asking supply: a session about a focus never sees that focus's own
unanswered bank questions, so the interviewer can't deliberately advance
the author's real goal — writing enough about the thing they're actually
here to build. The gap sat squarely inside the conversation interaction's
otherwise-tight scope (behavior.md rule 9: "build this person's vault —
nothing else"), and the owner ruled a deliberate, narrow widening rather
than a new interaction or a router change.

## Decision

**The scope is widened by exactly one capability, stated in the contract
and mirrored in `prompt/behavior.md` rules 3/6/9 and the Defaults.**
Conversations may now see and ask the session focus's own held bank
questions. Outside that one sliver, the deflection posture (rule 9) is
completely unchanged — this is not a general capability expansion.

**A new context block, `asking_supply`, sits between `record` and
`session`** (`context/manifest.md`, `interaction.yaml`'s `load_order`,
`conversation.ASSEMBLE_CONTEXT_BLOCK_ORDER`; the doc-drift parity test
forces all three to move together). It renders a header line — `Focus:
{label} — {answered} of {total} answered` — plus up to
`knob.asking_supply_top_k` (default 3) of that focus's own unanswered bank
questions, `[{qid}] {text}`. `budget.asking_supply` (400 tokens) caps the
BLOCK's own size only ("whisper, not flood" — prior-art caps apply to
render size, never to conversational usage, per the owner's own framing).

**Focus derivation is a ladder, not a lookup**
(`conversation._resolve_session_focus_and_candidates`): arc.question_id,
else any turn's `question_id` → `conversation._chain_root` (moved here
from `conversation_delivery.py` as the single authority both the ladder
and the turn-engine's own session-matching now share — recurring-defect
doctrine) → the qid's category letter →
`question_planner.build_focus_index()`'s `cat_to_focus` → the roadmap
focus object. Any rung failing (a story session's turns carry
`source_path`, never `question_id`; an unmapped category; the planner
itself unavailable) degrades to an honestly EMPTY block — never a
fabricated focus.

**Candidate ranking reuses the planner's own gates, never re-derives
them.** `question_planner.enriched_pending_questions` already folds
rumination-cooldown (×0.25) and escalation-gate (×0.05) weight multipliers
into every pending question's `weight`; the block's candidates are this
focus's own categories' pending rows from that SAME call, sorted by that
SAME weight, richest first. Declined-in-session ids are excluded before
ranking (below). No separate weighting logic exists for asking-supply.

**No per-session cap — quality-governed, not counter-governed (owner
ruling).** The protections that remain are entirely about respect, not
volume: a declined held question never returns this session (rule 4, made
structural), a cooled topic stays cooled (rule 13), and the escalation
gate (rule 7) still holds. The mission test and the naturalness evals are
what actually bound "how many" — a great conversation may hold several.

**The user-invitation hatch is semantic and fails toward asking (owner
ruling).** The turn's structured output gains two additive fields:
`user_invited_question: bool` (the worker's own judgment — an explicit
request or open-ended receptivity both count, and genuine uncertainty
resolves to `true`) and `held_question_id: str|null` (the ASKING_SUPPLY
qid actually asked, never trusted without checking membership in the
block). `conversation_delivery`'s blocking gate amends surgically: past
the ordinary exchange target, a question is permitted IFF
`user_invited_question` is true AND `held_question_id` is present in this
session's live `asking_supply_question_ids()` selection — resolved lazily,
only when the model actually named a qid, so the ordinary no-held-question
turn pays zero extra cost. An uninvited question past target is discarded
exactly as before (the existing `question_not_permitted` blocking lint);
within target, behavior is unchanged — a held question is simply one more
way to fill the turn's one question.

**Asked-question bookkeeping is a pick, not a delivery (consumption
semantics precedent — `questions/next`).** A held ask stamps the lifehug
turn's `question_id` to the held qid and marks it `asked_from_supply:
true`; no mint, no rotation mutation, no queue/ledger write — the bank
question already exists, and the reply files against it through the
existing turn-chain exactly like any other filed answer.

**Session-scoped decline memory is a deterministic rule, not a model
judgment.** `conversation_delivery._detect_declined_held_question`: when
the turn immediately before a user turn asked a held question
(`asked_from_supply: true`) and the new user turn's own `question_id`
doesn't match it, that qid is recorded via `conversation
.record_declined_questions` onto the session's additive
`declined_question_ids` field — excluded from that session's `asking_
supply` selection from that point forward (rule 4's "never re-offer" made
structural). This is deliberately SESSION-scoped, not global: a later,
separate session on the same focus starts with a clean slate — cross-
session decline state is out, reserved for future decisions-loop work.

**The block name.** "Open Questions" already means wiki-synthesized
questions in this codebase (`question_candidates.harvest_wiki_questions`)
— `asking_supply` names this block by what it actually is (the bank's own
unanswered supply for this focus) without colliding with existing
vocabulary.

**Coverage numbers ride in context but are never volunteered.** The
block's own header carries answered/total for the model's orientation;
`prompt/behavior.md`'s Defaults state plainly that this is context, not
copy — spoken only when the user actually asks about progress.

**Platform riders (recorded, not implemented here).** `conversation
.assemble_context`'s `blocks` override now accepts `"asking_supply"`
exactly like `"profile"`/`"record"` — the additive platform seam. The
hosted platform resolves this block's content from its own projections
(never the vault-local `question_planner` producer) and passes it through
that override; the worker-projection wiring that makes those projections
available is a platform-side prerequisite that rides the next pin bump,
alongside the envelope join with the filed-answers overlay so a picked-
not-delivered held question still reads correctly once the platform's own
answer path files it. Five new golden-property ids —
`held_question_offered_as_door`, `no_uninvited_question_past_target`,
`invitation_hatch_honored`, `empty_supply_honest_reply`,
`coverage_not_volunteered` — are FLAGGED for the platform's closed-
vocabulary reconciliation at that same pin bump.

## Consequences

- **Binds:** any future producer of a per-turn context block follows the
  same `blocks`-override-first pattern `asking_supply` establishes
  alongside `profile`/`record` — a vault-local OSS producer, an additive
  platform seam, never a runtime fork.
- **Binds:** `conversation._chain_root` is the one authority for the A14 →
  A14 / A14b → A14 suffix-chain-root computation; no module keeps its own
  copy.
- **Binds:** `question_planner.enriched_pending_questions`'s weight
  (rumination, escalation) is the one ranking authority for any future
  bank-question surfacing feature — never re-derived inline.
- **Forecloses:** a per-session usage cap on held questions — this is
  reserved language the owner explicitly ruled out; any future cap
  proposal needs its own ADR to reopen this ruling.
- **Forecloses:** a held question ever being minted, rotated, or queued
  like an ordinary follow-up — it is a pick from existing supply, always.
- **Delete-when:** the platform riders above are implemented and the five
  new property ids are reconciled into the platform's closed vocabulary —
  mark this section implemented at that pin bump, per the ADR 0014/0015
  precedent.

🤖 Generated with Claude Fable 5 via Claude Code
