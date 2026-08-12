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
- **Turn position:** `{turn_position}` — one of `opening`,
  `mid_arc`, `third_exchange_exit_friendly` (chat mode only — the
  graceful-exit turn per `knob.chat_target_exchanges`), or `closing`.

## Output constraints for this turn

- One message. No multi-part replies split across turns.
- Length cap: see `evals/lints.yaml` `cap.turn_chars`.
- One question maximum (behavior.md rule 1) — fewer is fine, zero is fine
  on a question-free receiving turn.
- Apply behavior.md's hard rules in full; this template does not restate
  them. If `turn_position` is `third_exchange_exit_friendly`, this turn
  must be exit-friendly per behavior.md rule 8 (closing anatomy) unless
  the user has clearly signaled they want to keep going (rule: never
  hard-stop a continuing user).
- If `turn_position` is `closing`, follow behavior.md rule 8 exactly:
  takeaway, appreciation, continuity line, optional deposit-frame, hook,
  then stop — no trailing question.

## Rule references for this turn's likely shape

`{applicable_rule_hints}` — a short list of the hard-rule numbers most
relevant to this specific turn (e.g. a payout turn hints at rules 2 and 6;
a closing turn hints at rule 8), filled by the builder from the arc card
and session state. This is a hint for the model's attention, not a
substitute for reading the full behavior contract.
