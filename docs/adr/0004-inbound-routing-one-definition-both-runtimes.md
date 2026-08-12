# ADR 0004: Inbound routing — five intents, one definition, both runtimes

Date: 2026-08-12
Status: proposed

## Context

Inbound message handling was prose-only: CLAUDE.md's "Recognizing Answers"
and AGENTS.md's "Answer Detection" told the host agent, in slightly
different words, how to guess what an inbound message was. There was no
way to delegate that judgment to a cheap model, no defined behavior for
out-of-scope input beyond "respond naturally, stay in character," and no
shared vocabulary the hosted platform's inbound router (Wave 3) could
target without re-deriving its own taxonomy. Meanwhile the biggest product
gap sat next to it: an unprompted story — the user's most generous act —
returned nothing but a CLI checkmark, while the actual conversational
response (`classify_story.py`) ran async, a week later.

Issue #117 (Wave 2 PR 4 of the Conversation Interaction build) closes both
gaps in one PR: `system/lifehug.py route` gives the host agent a delegable
classifier, and `system/ingest_story.py` gains an immediate Conversation
turn. This ADR records the routing half's binding decision — the turn-
engine half is ADR 0003's territory, reused here rather than copied
(issue #116, `conversation_delivery.run_post_answer_turn` /
`run_story_conversation_turn`).

## Decision

The inbound routing contract — the five-intent taxonomy (`answer`,
`new_story`, `command`, `continue_session`, `out_of_scope`), the
default-class rule (`continue_session` when a session is open), the
confidence threshold, and the deterministic safe-default order (pending
question → `answer`; else open session → `continue_session`; else ask
rather than guess) — lives in exactly one place:
`interactions/conversation/router/router.md` plus the threshold knob in
`interactions/conversation/interaction.yaml`
(`knob.router_confidence_threshold`). Every runtime that classifies inbound
messages — the OSS host-agent path (`lifehug.py route`,
`conversation_delivery.route_message`) and the hosted platform's inbound
webhook (Wave 3, `process_inbound`) — consumes this definition. Neither
runtime forks the taxonomy, the thresholds, or the default-class rule into
its own code or its own prose.

The ONE place the two runtimes are explicitly permitted to differ is the
unsure-fallback's *terminal* step — what happens when confidence is low,
no pending question exists, and no session is open. OSS asks one
clarifying line (`action:"ask_user"`); the hosted webhook runtime has no
synchronous round-trip to ask one, so it may resolve differently (platform
issue #422, not yet owner-ratified). router.md documents both branches as
the SAME definition's per-runtime terminal step — this is not a fork of
the contract, because the contract itself specifies both branches and the
reason (differing delivery mechanics) they can't share one mechanic.

`route` classifies; it never sends. The out-of-scope response
(`interactions/conversation/router/deflection.md`) is sent by the host,
once per exchange, then silence rather than a second or third repetition —
codifying the scope rule (chats and conversations build the vault, nothing
else) in place of "respond naturally, stay in character."

Alternatives considered. *Let each runtime keep its own prose*: rejected —
this is exactly the pattern that produced CLAUDE.md and AGENTS.md's
divergent 4-bucket lists in the first place, and the hosted platform would
have re-derived a third version. *Route synchronously through the same
model call on both runtimes*: rejected for the terminal step only — the
hosted webhook has no user-facing round-trip to ask a clarifying line
without either blocking the webhook or inventing a second async turn; OSS
does have one (the host agent is already in a synchronous exchange).

## Consequences

- **Binds:** any change to the five intents, the default-class rule, the
  threshold semantics, or the fixed intent→action mapping is made in
  `interactions/conversation/router/` and `interaction.yaml`, never in
  `lifehug.py`, `conversation_delivery.py`, CLAUDE.md, AGENTS.md, or
  `skill/SKILL.md` independently. The three prose surfaces restate the same
  contract; a prose-drift guard test (`test_prose_contracts_name_five_intents`)
  is a review-blocking tripwire, not a suggestion.
- **Binds:** `route_message` (and the platform's future `process_inbound`)
  read the threshold from `knob.router_confidence_threshold`, never a
  hardcoded literal — recurring-defect doctrine applies the same as the
  turn engine's `cap.turn_chars`.
- **Binds:** the deflection response is sent by the HOST, not by `route`
  itself — `route` stays a pure classifier so both runtimes can call it the
  same way regardless of how each one sends messages.
- **Forecloses:** a runtime silently guessing one of the five intents below
  threshold with no pending question and no open session. The contract's
  answer is always "ask, don't guess" — only the mechanics of asking differ
  by runtime.
- **Delete-when:** if platform issue #422 ratifies the hosted terminal-step
  behavior, this ADR is amended (not superseded) to record the ratified
  choice; the shared five-intent contract and threshold logic are unaffected
  either way.
