# ADR 0042: A question passes or it is not a question

Date: 2026-10-04
Status: ratified (owner, 2026-10-04 — "continue with the fix and full plan then merge on green"; lifehug-platform#984)

## Context

On 2026-10-04 the owner's daily question read **"update"**; the queue's next
card read **"gist"**. Both were literal bank entries, written in July by the
follow-up planner (`process_answer.append_followups`) when a model returned
one-word follow-ups, and queued on focus/category coverage by the weekly
planner. A scan of the owner's 400-entry bank found 23 machine-written entries
no person would ask: one-word follow-ups, a false premise narrated from the
vault's records ("…appears in your records only as a name…"), keystone probes
that volunteer "your answer places 8 timeline moments at once", Gmail-era
probes narrating the wiki, fourteen `When was {label}?` keystone templates
("When was wedding?", "When was MIT?", written by
`timeline_interaction.insert_keystone_question`), and one garbled probe. The
owner: *"when married isn't a good question"*; *"we should have an evaluation
for questions and these should fail them."*

The ranking did not catch them for two reasons. **It never saw them**:
`question_candidates.check_quality` and the unified quality score (ADR 0008)
ran only on the candidate path; the follow-up planner, the keystone minter and
the weekly queue wrote or ranked bank text without it. **Where it ran, it could
not fail anything**: it was a soft score — a one-word question lost 0.15 of
1.0, so a 0.9-priority "update" still cleared the 0.82 auto-promote line.

## Decision

**One evaluation, one door, verdicts not points.**

1. `question_craft.evaluate(text, context)` returns a **verdict** —
   `pass` / `review` / `fail` — with reasons. **Fail** is absolute and
   structural: fewer than five words; neither a question mark nor an
   imperative prompt (`question_craft.IMPERATIVE_OPENERS` — an imperative is a
   good question without a `?`); a raw label in a date template
   (`When was wedding?` — a label has no determiner and no `you`); an internal
   id or a slug (a digit, `node:<hex>`, or a slug the caller names — never a
   bare hyphen, so `day-to-day` is a word); a garbled repeat
   ("graduate from … graduation"); narrating the vault's records (v382's
   `NARRATES_RECORDS_PHRASES`, now defined here); narrating the system's
   leverage or coverage; a bare yes/no with no follow-through. **Review**: a
   5–7 word question that names nothing concrete, or an exact/near duplicate of
   a bank question. **Only a pass carries a score** — the unified quality
   score, which ranks among passes and never rescues a fail.
2. `question_bank.append_questions` is the **only** function that writes an
   open `- [ ] ` bank line. Follow-ups (`process_answer`, `gen_followups`),
   keystone probes (`timeline_interaction`) and candidate promotion
   (`candidate_promotion`, `question_candidates.insert_question`) all file
   through it. A fail is refused with its reasons and never written; a review
   is written with a `<!-- craft: review: … -->` comment. A guard test fails
   the build if any other module spells an open bank line.
3. A keystone probe is said in the domain's own words with the person as the
   subject (`When did you get married?`, `When did you move to {place}?`,
   `landmark_opportunities.SPAN_START_TEXTS` where the keystone names a
   domain). A label that cannot be phrased that way is refused, never
   templated.
4. The weekly queue re-evaluates every bank question and skips a fail
   (`skipped_craft_fail` in the plan); auto-promotion requires a pass (a fail
   is skipped whatever its priority; a review parks `craft_review`).
5. A question is **retired, never deleted**: `- [-] {id}: {text} *(retired
   DATE: reason)*`. `[-]` is neither open nor answered, so selection,
   planning, coverage and rotation never see it; every id allocator counts it,
   so an id is never reused; a retired work-item row reads as `dismissed`, so
   it is never minted again; a retired promoted row keeps a readable promotion
   marker. `question-bank-lint` lists every entry's verdict (read-only);
   `question-retire <id>` retires one.

Alternatives: **raising the soft penalties** — rejected, because any finite
penalty can be outbid by priority and the defect is categorical, not a matter
of degree. **Deleting failing lines** — rejected: the bank is the answer-once
ledger and ids are history; retirement keeps both. **A model judge at the
door** — rejected: the door must be deterministic so the hosted platform can
REPLAY it at send time, and a prompt is not a certifiable backstop (ADR 0028's
audit finding).

## Consequences

- Binds: every new bank writer goes through `question_bank.append_questions`;
  every new structural rule goes in `question_craft.fail_reasons` with a test
  that fires and a near-miss that does not.
- Binds: a rule that fails a good question is a bug — the rules are narrow on
  purpose (imperatives pass; `When was the kitchen fire?` passes; `When did the
  Calloways move?` passes).
- The existing penalty `narrates_records` stays in `check_quality` for the
  score path; the verdict is what gates.
- Host consequence (lifehug-platform#984): the platform pins this version and
  runs the same `evaluate` at send time through the REPLAY seam, so a stale
  queue cannot deliver a fail; Foundation ✗ binds to `question-retire`.
- Delete-when: never; supersede only if a better evaluation replaces this one
  at the same single door.
