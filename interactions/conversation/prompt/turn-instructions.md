# Turn instructions — assembled LAST

This template is assembled last in the per-turn context order (see
`context/manifest.md`), after identity, behavior, examples, and the
per-user and per-session context blocks. Everything durable — persona,
rules, defaults — lives in `prompt/identity.md` and `prompt/behavior.md`,
not here. This file is deliberately short: it is the freshest thing the
model reads before generating, and it should stay under a page.

`{placeholder}` slots are filled by PR 2's builder at runtime. This PR
ships the template only — no filling logic exists yet.

---

## This turn

- **Mode:** `{mode}` — `chat` or `conversation`.
- **Arc card intent:** `{arc_card_current_intent}` — the specific thing
  this turn is trying to draw out or land, per the planned arc (see
  `plan/arc-templates.md`). If no arc card is active, this is
  `{none — respond to what the user just said}`.
- **Previous turn:** `{previous_turn_summary}` — one line: what the AI
  said or asked last, and what (if anything) the user hasn't yet
  responded to.
- **Turn position:** `{turn_position}` — one of `opening`, `mid_arc`,
  `past_target` (chat mode only — past `knob.chat_target_exchanges`; our
  question-initiative is spent, so the turn simply receives, question-free,
  with no special framing about stopping), or `closing`.

## Output constraints for this turn

- One message. No multi-part replies split across turns.
- Length cap: see `evals/lints.yaml` `cap.turn_chars`.
- One question maximum (behavior.md rule 1) — fewer is fine, zero is fine
  on a question-free receiving turn.
- Apply behavior.md's hard rules in full; this template does not restate
  them. The exchange budget (`knob.chat_target_exchanges`) governs OUR
  initiative silently — past it, ordinary turns just keep receiving; there
  is no dedicated "offer to stop" turn (removed 2026-08-12, pure-chat wave
  — reply-is-consent makes it unnecessary: never hard-stop a continuing
  user, and never narrate that initiative has run out).
- If `turn_position` is `closing`, follow behavior.md rule 8 exactly:
  takeaway, appreciation, continuity line, optional deposit-frame, hook
  woven in naturally, then stop — no trailing question. The close is
  structured (ADR 0014): emit `{takeaway_prose, hook}`, never a labeled
  field, never commentary on the conversation itself, never an
  instruction addressed to a future turn — see the closing generation's
  own output-format appendix for the exact JSON shape.

## Rule references for this turn's likely shape

`{applicable_rule_hints}` — a short list of the hard-rule numbers most
relevant to this specific turn (e.g. a payout turn hints at rules 2 and 6;
a closing turn hints at rule 8), filled by the builder from the arc card
and session state. This is a hint for the model's attention, not a
substitute for reading the full behavior contract.
