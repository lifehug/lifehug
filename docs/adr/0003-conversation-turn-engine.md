# ADR 0003: Conversation turn engine replaces post-answer ack + follow-up

Date: 2026-08-11
Status: proposed

## Context

Answering a Lifehug question produced two disconnected messages. First a
warm acknowledgment that is contractually forbidden from asking anything —
`system/answer_ack.py` literally instructs "No questions back". Then, when
the adaptive-cadence gates allowed it, a second message carrying a question
picked by rotation from the bank: a different topic, a different voice, and
a header ("📖 Lifehug — since you're on a roll") that announces itself as a
prompt rather than a reply. The owner's words on issue lifehug#99 name the
failure directly — follow-ups have to read as conversation. `system/
research.md` §2e had already named the fix: "The fix is conversation, not
cadence — immediate acknowledgment + one listening follow-up."

Issue #114 shipped the behavior authority (`interactions/conversation/`) and
issue #115 shipped the session store, the prompt builders, and the
deterministic lint engine. Neither had a consumer: the post-answer pipeline
still ran the old pair. This ADR records the decision made in the
2026-08-11 owner-approved design session and implemented by issue #116 —
the decision to move the live post-answer path onto that infrastructure,
and the two guarantees that move is conditional on.

## Decision

`system/conversation_delivery.py` replaces the acknowledgment +
separate-follow-up pair in `process_answer.run_post_answer_delivery` with a
single **conversation turn**: one message that receives the answer, pays it
out, and cues the next question in the user's own words, per
`interactions/conversation/prompt/behavior.md`. Two properties of that
replacement are binding, not incidental:

1. **The fallback guarantee.** Any definitive failure — no seated provider,
   a provider error, an unparseable or lint-rejected generation, a
   definitive send rejection — degrades to today's exact behavior in the
   same invocation: `acknowledge_answer(...)` followed by
   `maybe_send_followup_question(...)`. The post-answer moment is never
   silent and never worse than it was before this change. The single
   exception is an *ambiguous* send: the turn may already have reached
   Telegram, so a fallback acknowledgment would risk speaking twice in two
   different voices; that case is ledgered and surfaced to the operator
   instead.
2. **The exactly-once ledger.** `state/conversation_deliveries.json` carries
   the same state machine as `state/answer_acknowledgments.json`: the
   conservative `ambiguous/send_in_progress` position is written *before*
   the external effect, a confirmed entry replays as a no-op with no second
   model call and no second send, and an ambiguous entry is never
   auto-retried — retrying it requires an operator who has checked Telegram
   (`conversation-turn-retry --confirm-not-sent`).

Alternatives considered. *Keep the ack and make only the follow-up
conversational*: rejected — the two-message shape is itself the defect the
owner named; a related question in a second message still reads as a prompt,
not a reply. *Retry generation on a lint failure*: rejected — a retry loop
against a live user costs latency and can produce a worse second attempt;
one attempt then fallback matches the acknowledgment layer's proven
behavior. *Extract a shared delivery-ledger module now*: deliberately
deferred — the recurring-defect doctrine's trigger is the second copy, and
Wave-2 PR 4's story turn will call this module rather than copy it.

## Consequences

- **Binds:** every future change to the post-answer path must preserve both
  guarantees above. Adding a new failure mode means adding it to the
  fallback path, not letting it fall through to silence. Changing the ledger
  means preserving pre-send ambiguity and the never-auto-retry rule.
- **Binds:** `answer_ack.py` / `answer_ack_delivery.py` are live code, not
  legacy. They are the fallback path and the keyless-mode path. The "No
  questions back" instruction stays: it is correct for an acknowledgment
  that is followed by a separate question.
- **Binds:** the runtime lints are `system/conversation_lints.py` reading
  `interactions/conversation/evals/lints.yaml`. The turn length cap is
  `cap.turn_chars` from that file — no module may pin an independent copy of
  that number.
- **Forecloses:** a second acknowledgment alongside a turn. One message per
  post-answer moment, whichever path produced it.
- **Forecloses:** closing-message nagging. Sessions below two user turns
  close silently; whatever was answered is already durably filed per turn.
- **Delete-when:** if the keyless host-agent path ever becomes the only
  supported runtime, the provider-readiness branch and its fallback collapse
  into one path and this ADR should be revisited.
