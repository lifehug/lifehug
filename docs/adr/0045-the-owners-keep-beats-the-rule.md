# ADR 0045: The owner's keep beats the rule

Date: 2026-10-15
Status: ratified (owner, 2026-10-15 — "fix the evaluator; give me Keep, Rewrite, Retire on a listed question"). Amends [ADR 0042](0042-a-question-passes-or-it-is-not-a-question.md).

## Context

ADR 0042 made the craft evaluation (`question_craft.evaluate`) absolute: a
FAIL is never filed, never queued, never promoted, and the hosted platform
replays the same function at send time. Its own module docstring set the
contract that keeps that safe: *a rule that fails a good question is worse than
no rule; every rule narrow.*

On 2026-10-15 the Foundation "Needs attention" list (lifehug-platform #984)
showed seven OPEN questions from the owner's bank as craft FAILs — and all
seven are good questions:

| id | reason | shape |
|----|--------|-------|
| A57 | `not_a_question` | a quote, then "— tell me about one specific moment…" |
| C21 | `garbled_repeat` | "moments with your grandmother … one single moment" |
| D20 | `not_a_question` | a statement, then "— tell me about one day when…" |
| G8 | `not_a_question` | a statement. "Where did you and AJ build this?" … "Walk me through the process." |
| M13 | `not_a_question` | "You named your son James. Tell me about that decision." |
| P11 | `not_a_question` | a quote, then "— tell me about one specific thing she did…" |
| R7 | `not_a_question` | a statement. "Tell me about one specific afternoon…" |

Six failed `not_a_question` because the test was "the FIRST sentence ends with
?, or the TEXT opens with an imperative": a statement-then-question or a
quote-then-imperative was read as no question at all. One failed
`garbled_repeat` because "moments … moment" was paired as a stem and its
nominalization ("moment" ends in *-ment*). Both are rules failing good
questions. And the owner had no verb but Retire: nothing let him say "this
one is fine" or fix a wording in place.

## Decision

**Fix the evaluator, narrowly** (`system/question_craft.py`):

- `A_QUESTION_ANYWHERE_IS_A_QUESTION` — `not_a_question` fires only when NO
  sentence ends with "?" and NO clause opens with an imperative opener. A
  clause opens at the start of the text, after `. ! ?`, after a dash (— – or a
  spaced hyphen), a colon or a semicolon, optionally behind an opening quote.
- `A_PLURAL_IS_NOT_A_NOMINALIZATION` — `garbled_repeat` never pairs a word with
  its own plural, and pairs a stem with its nominalization only where the
  LONGER word carries the suffix and the shorter one does not ("graduate …
  graduation" still fails).

**Give the owner three verbs on a listed question** — Retire (ADR 0042),
and:

- **Keep** — `A_KEPT_QUESTION_IS_THE_OWNERS_PASS` /
  `question_bank.THE_OWNERS_KEEP_IS_ON_THE_ROW`. `lifehug.py question-keep ID
  [--reason]` writes `  <!-- craft: kept DATE: reason -->` under the open row
  (replacing an earlier keep and a `craft: review:` comment). `evaluate(text,
  context={"kept": True})` is then a PASS with `reasons: []`, its score, and an
  additive `overridden` list of what the rules would have said. Every caller
  that re-evaluates a bank row passes `kept`: `question_bank.lint_bank`,
  `question_planner.drop_craft_fails`, and the hosted send-time gate, which
  replays `evaluate` and must thread `kept` from the row.
- **Rewrite** — `question_bank.A_REWRITE_IS_THE_SAME_QUESTION_RESAID`.
  `lifehug.py question-rewrite ID --text "…"` re-says the open row in place
  (same id, position, box), after evaluating the new text against the bank: a
  FAIL is refused (`CraftRefused`, nothing written), a REVIEW is filed with a
  fresh review comment, a PASS clean. Prior review/kept comments are dropped;
  `  <!-- craft: rewritten DATE: was "…" -->` keeps the old text; a promoted
  row's promotion marker is re-stamped for the new bytes
  (`candidate_promotion.restamp_marker_question`).

Alternatives: a per-rule allowlist of exempt texts (lost — the bug was the
rules, and an allowlist hides the next false positive); auto-keeping every
promoted question (lost — the owner, not the pipeline, makes the exception).

## Consequences

- Binds: any new reader of bank rows that re-runs `evaluate` must pass `kept`
  for a kept row (read `question_bank.craft_kept_index`). The platform's pin of
  the package, its send-time gate, and its "Needs attention" Review lane must
  surface Keep / Rewrite / Retire and honor `kept`.
- Binds: the kept grammar is a provenance comment on the line after the row;
  `fail_reasons` / `review_reasons` stay pure — they report what the rules see,
  and only `evaluate` applies the owner's keep.
- Forecloses: widening `not_a_question` or `garbled_repeat` to catch a shape
  without a golden negative AND the seven positives still passing
  (`tests/test_question_craft.py`).
- Revisit when: a kept question turns out to need a rule exemption the owner
  did not grant (then the keep is too broad), or a rewrite needs to change a
  row's category (that is Retire + a new question, not a rewrite).
