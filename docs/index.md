---
title: Home
nav_order: 1
---

# How Lifehug Works

Lifehug is a lifelong AI oral-history system organized around **the
Loop**: daily answers become durable sources, sources become a private
wiki and structured signals, signals become better questions, and better
questions deepen the life story.

This site is the **handbook of its mechanics** — one page per feature,
each answering the same questions in the same order, so that anyone
(including a future maintainer with zero context) can read one page and
hold that feature's complete picture:

1. **What it does & what it's for** — the feature's job, and the main
   use case told from the user's seat.
2. **The nouns** — every term the feature owns, defined once, linked to
   the [Glossary]({% link handbook/glossary.md %}).
3. **How it works** — the mechanism: lifecycle, clock, files.
4. **The algorithm** — the real formula with the real numbers, and a
   worked example.
5. **In the loop** — what feeds it, what it feeds, how it self-improves,
   and its [Convergence Principle](https://github.com/lifehug/lifehug/blob/main/docs/adr/0006-convergence-principle.md)
   classification (floor or accelerator).
6. **Where it lives** — code map, state files, commands, guard tests.
7. **Decisions** — the ADRs and owner rulings that bind it.

## Kept honest by construction

Two structural guarantees keep this site from drifting into fiction:

- **Interaction pages embed their `behavior.md` files** — in the
  Interaction pattern the documentation *is* the prompt, so those pages
  cannot disagree with what the model is actually told.
- **Every quoted algorithm number is parity-tested.** Handbook pages
  annotate their numbers with an HTML comment of the shape
  `parity: <module>.<CONSTANT> = <value>`, and
  `tests/test_handbook_parity.py` asserts each against the live
  constant — a code change that moves a number fails CI until the page
  moves with it.

For example, the candidate auto-promotion bar quoted across this site is
**0.82** <!-- parity: question_candidates.AUTO_PROMOTE_THRESHOLD = 0.82 -->
and the focus-idea ready floor is
**8.0** <!-- parity: recommend_focuses.FOCUS_READY_SCORE_FLOOR = 8.0 --> —
both statements are enforced, not remembered.

## The raw record

The [ADRs](https://github.com/lifehug/lifehug/tree/main/docs/adr) are the
binding decision log and the [pr-specs](https://github.com/lifehug/lifehug/tree/main/docs/pr-specs)
are the contracts features were built against. Handbook pages link into
them; they remain the authority when prose and record disagree.
