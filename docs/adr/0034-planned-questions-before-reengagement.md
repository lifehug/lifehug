# ADR 0034: Planned questions precede quiet re-engagement

Date: 2026-09-15
Status: ratified (owner, 2026-09-15)

Generated with gpt-5.6-sol via Codex

## Context

A daily delivery selected a short bank label while the healthy weekly queue
held a complete planned question. Read-only diagnosis found that thirteen days
without an answer activated quiet re-engagement before the queue was read; the
re-engagement selector then faithfully chose the least-delivered shortest
eligible bank row. The planner, bank parser, and delivery renderer had not
failed.

PR #332 retained silence as an override even when the queue was healthy. The
contract for PR #341 and the hosted twin PR #849 reverse that precedence: a
current plan is the deliberate ordering authority, including after a quiet
stretch.

## Decision

The canonical selector in `system/ask.py` uses one order:

1. Return the first queued, unanswered bank question from a non-expired
   planned queue.
2. If no planned question is usable and the silence threshold is met, select
   through the existing quiet re-engagement policy.
3. Otherwise, select through the existing ordinary rotation policy.

This supersedes PR #332's healthy-queue silence override. It does not change
queue expiry or status handling, bank eligibility, answered state, delivery
counts, the four-day default threshold, re-engagement scoring, or ordinary
rotation fairness. Delivery remains distinct from an answer, and selection
does not write state.

## Consequences

- A planned queue may deliberately lead with a serious subject after a quiet
  stretch; its ordering is authoritative until it has no usable question.
- Missing, expired, exhausted, sent, answered, and dangling queue entries keep
  the same fallback behavior they had before this decision.
- No minimum length, punctuation rule, blacklist, bank rewrite, second
  selector, or model judgment is introduced. A brief approved prompt remains
  eligible, including when it is the sole fallback.
- Revisit this order only if the planner stops representing an intentional,
  current delivery plan; a single undesirable bank entry is not such a change.
