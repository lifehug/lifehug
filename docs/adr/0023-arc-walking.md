# ADR 0023: Arc walking — episodes of a recomputed plan

Date: 2026-08-22
Status: proposed

## Context

The package has two ways to ask: the daily single question (`ask.py` →
`daily_question.sh`), and a chat's advisory `asking_supply` block (ADR 0016),
which offers the top-K held bank questions and lets the model ask one *when
invited*. Both are deliberately quiet. Neither can serve the posture platform
issue #570 describes, in the owner's words: pressing Play on a focus, a
chapter, or a book "starts a conversation that will start to answer every open
question… I'm committing to answering a lot… find arcs between the questions to
have a casual conversation."

Nothing in the package can express that commitment. `arc_planner.plan()` writes
one card per queued question — an opening plus 2–4 typed intents, expiring with
the week — so a focus with eleven open questions gets eleven unrelated cards and
no order at all. There has never been a multi-question plan object. And nothing
names which question an ANSWER answered: the structured turn output carries
`held_question_id` (the qid the model *asked*, stamped onto the assistant turn),
but a story that answers question three while question one is on the table has
nowhere to say so.

Two failure modes made this a decision rather than a default. A plan that is
STORED becomes a checklist the person is measured against and that goes stale
the moment they answer something elsewhere. And a session that walks a plan to
exhaustion becomes a form — the owner's explicit fear: "moments where it can
leave and come back later… not feel like they're missing something if they
leave."

## Decision

Add `arc_walk`, the fourth child Interaction of Conversation
(`interactions/arc_walk/`, `system/arc_walk.py`), with one goal: **work a
target's open questions casually, in resumable episodes.**

1. **The plan is a map, not a script, and it is never persisted.** At every
   Play, `arc_walk.build_arc_plan` recomputes the target's open questions from
   the bank, ordered by `question_planner.enriched_pending_questions`' weights
   and `build_queue`'s own weight expression and `arc_max` streak cap — the one
   ranking authority, reused rather than re-derived. Answered questions fall out
   because the plan is rebuilt, so the only durable memory an episode leans on
   is the one that already exists, `session["declined_question_ids"]` (ADR
   0016). Resuming is a new episode of a fresh plan.
   *Alternative rejected*: a focus-level card written into
   `state/arc_cards.json` by the weekly `arc-plan` step (issue #570's own first
   suggestion). It is a writer change with its own expiry and merge semantics,
   and it would go stale exactly where recomputation cannot.
2. **The opener announces the agenda; the model then follows the person.**
   Pre-generating the order and letting the model deviate is the whole design:
   one warm sentence naming what today is about, then the first question, then
   tangents followed rather than corrected and declines skipped silently.
   *Alternative rejected*: driving the plan turn-by-turn from the engine, which
   would make the conversation a form.
3. **Episodes, not marathons.** One session walks about four to eight questions
   (`EPISODE_SIZES`: basic 4 / standard 6 / extreme 8, also manifest knobs), and
   closes warmly with what was covered and the fact that the rest waits. No
   checklist, no streak, and nothing is ever described as unfinished. The
   maximum episode (12) sits well under `knob.conversation_turn_cap_exchanges`
   (25) so an episode always ends on its own terms.
4. **Filing is per question, and the "asked qid" concept is not duplicated.**
   The qid the previous assistant turn asked is `turn["question_id"]` on a
   `role: "lifehug"` turn — what the model calls `held_question_id` and what the
   hosted platform calls `stamped_question_id`. `arc_walk.asked_question_id` is
   the one reader. Exactly one additive turn-output field,
   `answered_question_id`, lets an answer that landed on a different agenda
   question say so. **Primary only**: an answer covering two names one, and the
   compiler cross-links the rest by content.
5. **Passive users are untouched.** The daily single question keeps working
   exactly as it did. This Interaction runs only when a target carrying N
   questions is Played — by a person today, by the scheduler later.
   Mechanically: `TurnShape.arc_stage` defaults to `None`, and with it `None`
   the output-contract appendix is byte-identical to v192. A required test
   pins that, so the passive path cannot drift by one byte.

## Consequences

- **Binds.** Any host walking a target REPLAYs this package's leaf and reads
  the names in `interactions/arc_walk/README.md`'s Platform-twin table; it does
  not re-implement the ordering, the stage, the episode size, or the
  validation. The plan's `plan_n`/`answered_k` are bank facts — "k of N" on a
  Foundation row is computed from the bank, never from a stored counter.
- **Binds.** `arc_walk`'s ordering is `enriched_pending_questions` +
  `build_queue`'s weight expression + `arc_max`. Two AST pins fail the build if
  either drifts, because a Play that ranks differently from the week is two
  planners.
- **Forecloses.** A persisted plan object, a per-session question cap, a
  progress counter in the visible reply, and a second "which question was
  asked" field. All four are off the table unless this ADR is superseded.
- **Deliberately deferred, not smuggled.** Issue #570's two noted gaps — a
  focus-level weekly arc card, and stamping queue-item `status` when a Play
  answers it — are named in the contract's Scope as out, with reasons.
  `build_arc_plan` is the function a future weekly pre-warm would call.
- **Delete-when.** If the daily loop becomes a scheduled Play for every user
  (issue #570 P4), ruling 5's "passive users are untouched" stops being a
  constraint and becomes a description of one target kind; this ADR should then
  be revisited rather than quietly outgrown.
