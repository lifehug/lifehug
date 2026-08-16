# Contract: content-first-close

## Why

Owner-hit live, second closing incident in two days, one root cause the
audit proved: **`build_closing_prompt` has never seen the conversation.**
Since the pure-chat wave it consumes only `mode` + `rolling_summary` — a
field the hosted platform never writes and that, even when written,
never contains the message being replied to. Every model-generated close
has therefore been STARVED: yesterday the starvation presented as
confabulation (invented claims about the author's behavior — the #163
close's "you pushed back a couple of times" was fiction) plus scaffolding
leak; today, post-#164's format fix, it presented as an honest
description of emptiness ("showing up with nothing yet to say") delivered
to a man who had just written a three-hundred-word Seattle memory. #164's
format contract held perfectly; the prompt was never built right.

Owner-ratified direction: the conversation interaction does ONE thing
well — respond to what the person actually said — and a model with
nothing to see never speaks.

## Binding facts (as of origin/main v177)

- The builder: `system/conversation.py::build_closing_prompt(payload)` —
  reads `payload["session"]` `.get("mode")` / `.get("rolling_summary")`
  ONLY; the `{takeaway_prose, hook}` wire contract is appended by the
  caller (`conversation_delivery._closing_output_contract()`), split
  unchanged by this PR.
- The engine: `conversation_delivery.py` — `close_session_now()` builds
  the closing prompt from the session doc; post-#164 it parses
  structured output and degrades to SILENCE on parse/lint failure
  (blocking posture already correct OSS-side).
- Session docs (`state/conversations/<id>.json`) carry full `turns`
  (role/text/ts/channel); `rolling_summary` optional.
- The platform executes this builder verbatim via subprocess REPLAY
  (`conversation_prompt.py`), passing a projection whose `turns` are
  already populated — the fix flows to hosted through the pin with zero
  platform prompt logic (the platform's ADVISORY lint posture is a
  separate platform rider, out of scope here, recorded in the ADR).
- Context budgets: `interactions/conversation/context/manifest.md` +
  `interaction.yaml` `budget.*` — the transcript block must respect a
  budget like every other block (flat scalar YAML).
- behavior.md is byte-embedded in
  `docs/handbook/interactions/conversation.md`
  (tests/test_handbook_parity.py EmbedParityTests) — edits move in
  lockstep.
- The eval harness: `interactions/conversation/evals/` — goldens carry
  per-turn `properties`; the platform mirrors the property vocabulary in
  a closed set (a NEW property id must be flagged in the PR body for the
  next pin bump's reconciliation — the tests/llm surface).
- 21 pre-existing env failures on clean origin/main in this workspace;
  zero delta; CI arbiter. Version bumps to next free (expect 178);
  changelog STRING.

## Scope

1. **The builder reads the conversation (fix A).**
   `build_closing_prompt` gains the transcript from
   `session["turns"]`: the FINAL USER TURN verbatim (never truncated
   away — it is the reason a reply is owed), preceded by recent turns
   within a new manifest budget (`budget.closing_transcript`, default
   sized like the turn prompt's transcript allowance), plus
   `rolling_summary` when non-empty (older context the window dropped).
   Instruction hierarchy REWRITTEN in the same spirit as rule 8: the
   close RESPONDS TO THE FINAL MESSAGE FIRST — receipt and payout of
   what was just shared, exactly as a normal turn would — and lets that
   response settle into the single woven takeaway that lands the
   thread. A close that ignores what was just said is a defect.
2. **The starvation guard (fix B).** The builder RAISES
   (`ConversationPromptError`-family, its existing failure vocabulary)
   when the session has no user turns AND no non-empty rolling summary
   — it never emits a prompt that asks a model to appreciate nothing.
   Engine degradation, both call classes:
   - budget-reached closing beat (a user message is in hand): fall back
     to the NORMAL turn prompt — the person gets a real reply; the
     thread lands another day;
   - sweep/idle/day closes of an empty session: SILENCE (the existing
     no-takeaway close path) — the session closes, nothing is sent.
3. **behavior.md rule 8 amendment (fix E carried with it)**: the
   respond-first clause plus the prime directive stated at the rule's
   head: the conversation surface speaks only ABOUT THE AUTHOR'S OWN
   CONTENT, to the author; a turn with no content to speak about is
   silence, not invention. Handbook embed updated in lockstep.
4. **Evals (fix D).**
   - New golden PASS: a session whose long final user message trips the
     budget → the close's properties include NEW
     `closing_engages_final_message` (asserted by content overlap with
     the final turn — the property checker implements a concrete
     verifiable check, e.g. references at least one distinctive
     content token from the final user turn; keep the checker honest
     and simple).
   - New deterministic test (not a golden): empty-session close →
     builder refuses → engine silence.
   - The synthetic #163-shaped and today-shaped fixtures stay/extend as
     lint-failure cases.
   - FLAG in the PR body: `closing_engages_final_message` is a NEW
     property id — the platform's closed vocabulary reconciles at the
     next pin bump.
5. **ADR 0015**: content-first close + starvation refusal — the two
   incidents, the root cause (summary-only builder + never-written
   summary), the respond-first hierarchy, the budget, the degradation
   table, the platform riders (blocking posture for the close class +
   vocabulary reconciliation + the regression test from the audit's
   reproduction).
6. Version bump + changelog; `interaction.yaml` gains the new budget
   knob; no new vault state.

Out: platform changes (pin-bump riders per ADR 0015) · rolling-summary
computation anywhere (the transcript window makes it optional; a future
summary feature is its own decision) · any change to normal-turn
behavior.

## Test plan

`tests/test_content_first_close.py` (new), subtests: builder includes
the final user turn verbatim (long message never truncated away);
respects `budget.closing_transcript` for earlier turns (oldest dropped
first); includes rolling_summary when present; REFUSES on no-user-turns
+ no-summary; budget-beat degradation falls to the turn prompt (person
gets a normal reply); sweep-close degradation is silence; the
`closing_engages_final_message` checker passes/fails correctly on
crafted closes; prompt instruction contains the respond-first clause.
Update `test_structured_close.py` fixtures where they pinned the
summary-only prompt shape. `conversation-evals` keyless layers green.
EmbedParityTests green (handbook lockstep). Zero delta vs the
21-failure baseline; CI arbiter.

## Definition of done

Per TEMPLATE.md: version bump, ADR 0015, behavior.md + handbook embed
lockstep, manifest budget documented, the new-property flag in the PR
body, evidence comment with a real keyless closing-prompt build over a
Seattle-shaped synthetic session (long final message visible in the
printed prompt) AND a refused empty-session build. Closes the incident
class; references issues #163's ADR and the platform incident of
2026-08-16.

🤖 Contract authored by Claude Fable 5 via Claude Code
